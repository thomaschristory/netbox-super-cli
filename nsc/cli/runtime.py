"""Runtime context, profile resolution, exit-code mapping.

`RuntimeContext` carries the live `NetBoxClient`, command model, config, and
output preferences for a single invocation. It is populated by the bootstrap
pipeline in the root Typer callback and consumed by the dynamic handlers.
"""

from __future__ import annotations

import itertools
import sys
import uuid
from collections.abc import Iterable, Iterator, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, HttpUrl, SkipValidation, ValidationError

from nsc.auth.keyring_store import KeyringStoreError, resolve_token
from nsc.branching.errors import (
    BranchAmbiguousError,
    BranchConflictError,
    BranchError,
    BranchJobFailedError,
    BranchJobTimeoutError,
    BranchNotFoundError,
    BranchNotReadyError,
)
from nsc.cache.store import ADHOC_PROFILE
from nsc.config.models import ColorMode, Config, ObjectColorMode, OutputFormat, Profile
from nsc.config.settings import default_paths
from nsc.http.client import NetBoxClient
from nsc.http.errors import NetBoxAPIError, NetBoxClientError
from nsc.model.command_model import CommandModel, Operation
from nsc.output.errors import (
    EXIT_CODES,
    ErrorEnvelope,
    ErrorType,
    RenderTarget,
    render_to_json,
    render_to_rich_stderr,
    select_render_target,
)

# Named constants to satisfy PLR2004 (no magic numbers in comparisons).
_STATUS_UNAUTHORIZED = 401
_STATUS_FORBIDDEN = 403
_STATUS_NOT_FOUND = 404
_STATUS_CONFLICT = 409
_STATUS_TOO_MANY = 429
_STATUS_4XX_MIN = 400
_STATUS_5XX_MIN = 500


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CLIOverrides(_Frozen):
    profile: str | None = None
    url: str | None = None
    token: str | None = None
    insecure: bool | None = None
    schema_override: str | None = None
    refresh_schema: bool = False
    output: str | None = None
    object_colors: bool | None = None
    branch: str | None = None


# Reserved selector: forces main even when the profile has a sticky branch.
MAIN_BRANCH = "main"


class BranchSelection(_Frozen):
    name: str
    source: Literal["flag", "env", "profile"]


class ResolvedProfile(_Frozen):
    name: str
    url: HttpUrl
    token: str
    verify_ssl: bool
    timeout: float
    schema_url: HttpUrl | None


class NoProfileError(Exception):
    """No URL/token available from any source."""


class UnknownProfileError(Exception):
    """A profile was requested by name but is not in the config."""


class InvalidURLError(ValueError):
    """A --url/NSC_URL (or schema URL) override is not a valid http(s) URL."""

    def __init__(self, value: str, *, source: str, what: str = "NetBox URL") -> None:
        super().__init__(
            f"invalid {what} {value!r} (from {source}); expected http(s)://host[/path]"
        )
        self.value = value
        self.source = source


def _resolve_ssl_and_timeout(
    config: Config,
    overrides: CLIOverrides,
    env: Mapping[str, str],
    base: Profile | None,
) -> tuple[bool, float]:
    insecure_env = _bool_env(env.get("NSC_INSECURE"))
    if overrides.insecure is not None:
        verify_ssl = not overrides.insecure
    elif insecure_env is not None:
        verify_ssl = not insecure_env
    elif base is not None:
        verify_ssl = base.verify_ssl
    else:
        verify_ssl = True
    timeout = base.timeout if (base and base.timeout is not None) else config.defaults.timeout
    return verify_ssl, timeout


def resolve_transport_settings(
    config: Config,
    overrides: CLIOverrides,
    env: Mapping[str, str],
) -> tuple[bool, float]:
    """Compute (verify_ssl, timeout) without requiring URL/token.

    Used by meta commands like `nsc commands` that fetch a schema directly but
    don't need a fully-resolved profile. Honours `--insecure`, `NSC_INSECURE`,
    and the active profile's `verify_ssl`/`timeout` in the same precedence
    order as `resolve_profile`.
    """
    name = overrides.profile or env.get("NSC_PROFILE") or config.default_profile
    base = config.profiles.get(name) if name else None
    return _resolve_ssl_and_timeout(config, overrides, env, base)


def resolve_profile(
    config: Config,
    overrides: CLIOverrides,
    env: Mapping[str, str],
) -> ResolvedProfile:
    base, base_name = _select_base_profile(config, overrides, env)

    url_choice = _first_set_with_source(
        (overrides.url, "--url"),
        (env.get("NSC_URL"), "NSC_URL"),
        (str(base.url) if base else None, f"profile {base_name}"),
    )
    # Flag/env overrides win before the keyring is consulted, so `--token`
    # works even when the profile's `!keyring` entry or backend is missing.
    token = _first_set(overrides.token, env.get("NSC_TOKEN"))
    if token is None and base is not None:
        token = _first_set(resolve_token(base))
    if url_choice is None or token is None:
        raise NoProfileError(
            "no NetBox URL/token configured (set NSC_URL+NSC_TOKEN, "
            "pass --url and --token, or configure a profile in ~/.nsc/config.yaml)"
        )

    verify_ssl, timeout = _resolve_ssl_and_timeout(config, overrides, env, base)

    schema_choice = _first_set_with_source(
        (_url_only(overrides.schema_override), "--schema"),
        (_url_only(env.get("NSC_SCHEMA")), "NSC_SCHEMA"),
        (str(base.schema_url) if base and base.schema_url else None, f"profile {base_name}"),
    )

    return ResolvedProfile(
        name=base_name,
        url=_parse_url(*url_choice),
        token=token,
        verify_ssl=verify_ssl,
        timeout=timeout,
        schema_url=_parse_url(*schema_choice, what="schema URL") if schema_choice else None,
    )


def resolve_schema_override(overrides: CLIOverrides, env: Mapping[str, str]) -> str | None:
    """`--schema` wins over `NSC_SCHEMA`; either may be a local path or a URL."""
    return _first_set(overrides.schema_override, env.get("NSC_SCHEMA"))


def resolve_branch_selection(
    config: Config,
    overrides: CLIOverrides,
    env: Mapping[str, str],
) -> BranchSelection | None:
    base, _ = _select_base_profile(config, overrides, env)
    profile_branch = base.branch if base else None
    if ignored_profile_branch(config, overrides, env) is not None:
        profile_branch = None
    candidates: list[tuple[str | None, Literal["flag", "env", "profile"]]] = [
        (overrides.branch, "flag"),
        (env.get("NSC_BRANCH"), "env"),
        (profile_branch, "profile"),
    ]
    for value, source in candidates:
        if value:
            return None if value == MAIN_BRANCH else BranchSelection(name=value, source=source)
    return None


def ignored_profile_branch(
    config: Config, overrides: CLIOverrides, env: Mapping[str, str]
) -> str | None:
    """The profile's sticky branch, when --url/NSC_URL points at another server."""
    base, _ = _select_base_profile(config, overrides, env)
    if base is None or not base.branch:
        return None
    url_override = _first_set(overrides.url, env.get("NSC_URL"))
    if url_override is None or same_server(url_override, base.url):
        return None
    return base.branch


def _select_base_profile(
    config: Config, overrides: CLIOverrides, env: Mapping[str, str]
) -> tuple[Profile | None, str]:
    name = overrides.profile or env.get("NSC_PROFILE") or config.default_profile
    if name is None:
        return None, ADHOC_PROFILE
    if name not in config.profiles:
        raise UnknownProfileError(f"profile {name!r} is not defined in ~/.nsc/config.yaml")
    return config.profiles[name], name


def same_server(raw: str, url: HttpUrl) -> bool:
    try:
        parsed = HttpUrl(raw)
    except ValidationError:
        return False
    return str(parsed).rstrip("/") == str(url).rstrip("/")


def _first_set_with_source(*candidates: tuple[str | None, str]) -> tuple[str, str] | None:
    for value, source in candidates:
        if value is not None and value != "":
            return value, source
    return None


def _parse_url(value: str, source: str, *, what: str = "NetBox URL") -> HttpUrl:
    try:
        return HttpUrl(value)
    except ValidationError:
        raise InvalidURLError(value, source=source, what=what) from None


def _first_set(*values: str | None) -> str | None:
    for v in values:
        if v is not None and v != "":
            return v
    return None


def _bool_env(raw: str | None) -> bool | None:
    if raw is None:
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _url_only(value: str | None) -> str | None:
    """Return the value only if it looks like an HTTP(S) URL; else None.

    `--schema`/`NSC_SCHEMA` may be a local path, in which case it should not
    populate the profile's `schema_url` (which is HttpUrl-validated). The
    schema_override flow consumes the raw value via `resolve_schema_override`.
    """
    if not value:
        return None
    if value.startswith(("http://", "https://")):
        return value
    return None


def resolve_color(mode: ColorMode, *, is_tty: bool) -> bool:
    if mode is ColorMode.ON:
        return True
    if mode is ColorMode.OFF:
        return False
    return is_tty


def resolve_object_colors(mode: ObjectColorMode, *, color: bool) -> bool:
    """Resolve whether NetBox-native object colors render.

    Always gated by the global `color` resolution (no ANSI when color is off),
    but can be disabled independently: OFF turns object colors off while status
    coloring stays on; ON/AUTO follow `color`.

    Contract: ON is deliberately *not* a force — it stays identical to AUTO so
    that `--object-colors` (and `NSC_OBJECT_COLORS=on`) can never override the
    no-color decision (`--no-color`, `NO_COLOR`, non-tty). Only OFF diverges.
    """
    if mode is ObjectColorMode.OFF:
        return False
    return color


class RuntimeContext(BaseModel):
    """Per-invocation runtime state.

    Not frozen because `client` (a NetBoxClient wrapping httpx2.Client) is mutable.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    resolved_profile: ResolvedProfile
    branch: BranchSelection | None = None
    config: Config
    command_model: SkipValidation[CommandModel]
    client: SkipValidation[NetBoxClient]
    output_format: OutputFormat
    debug: bool = False
    page_size: int = 50
    columns_override: list[str] | None = None
    filters: list[tuple[str, str]] = []
    limit: int | None = None
    fetch_all: bool = False
    compact: bool = False
    color: bool = False
    color_stderr: bool = False
    object_colors: bool = False
    apply: bool = False
    explain: bool = False
    strict: bool = False
    file: str | None = None
    fields: list[str] = []
    file_format: str | None = None
    bulk: bool | None = None
    no_bulk: bool | None = None
    on_error: Literal["stop", "continue"] = "stop"
    workers: int = 1

    def resolve_columns(self, tag: str, resource: str, operation: Operation) -> list[str] | None:
        if self.columns_override is not None:
            return self.columns_override
        per_tag = self.config.columns.get(tag, {})
        configured = per_tag.get(resource)
        if configured is not None:
            return configured
        return operation.default_columns


def apply_limit(
    iterator: Iterable[dict[str, Any]],
    *,
    limit: int | None,
    fetch_all: bool,
    page_size: int,
) -> Iterator[dict[str, Any]]:
    cap: int | None
    if limit is not None:
        cap = max(limit, 0)
    elif fetch_all:
        cap = None
    else:
        cap = page_size
    # islice stops before pulling record cap+1, so a lazy pager never fetches
    # a page whose records would only be discarded.
    yield from itertools.islice(iterator, cap)


def truncation_notice(
    rows: int, source: object, *, limit: int | None, fetch_all: bool
) -> str | None:
    """Stderr hint when the default page-size cap hid records the server still has."""
    if limit is not None or fetch_all or getattr(source, "has_more", False) is not True:
        return None
    total = getattr(source, "total", None)
    shown = f"{rows} of {total}" if isinstance(total, int) else f"the first {rows}"
    return f"nsc: showing {shown} results; pass --all to fetch everything or --limit N."


def _audit_log_path() -> str | None:
    p = default_paths().logs_dir / "audit.jsonl"
    return str(p) if p.exists() else None


def _api_error_type(status_code: int) -> ErrorType:
    if status_code in (_STATUS_UNAUTHORIZED, _STATUS_FORBIDDEN):
        return ErrorType.AUTH
    if status_code == _STATUS_NOT_FOUND:
        return ErrorType.NOT_FOUND
    if status_code == _STATUS_CONFLICT:
        return ErrorType.CONFLICT
    if status_code == _STATUS_TOO_MANY:
        return ErrorType.RATE_LIMITED
    if _STATUS_4XX_MIN <= status_code < _STATUS_5XX_MIN:
        return ErrorType.VALIDATION
    return ErrorType.SERVER


def map_error(
    exc: BaseException,
    *,
    operation_id: str | None = None,
    attempt_n: int | None = None,
    branch: str | None = None,
) -> ErrorEnvelope:
    """Translate a known nsc exception into an ErrorEnvelope. Unknown → internal.

    `branch` (the active branch, if any) is recorded in `details` so a failure
    says which branch it happened in.
    """
    env = _map_error(exc, operation_id=operation_id, attempt_n=attempt_n)
    if branch is None or "branch" in env.details:
        return env
    return env.model_copy(update={"details": {**env.details, "branch": branch}})


def _map_error(
    exc: BaseException,
    *,
    operation_id: str | None,
    attempt_n: int | None,
) -> ErrorEnvelope:
    if isinstance(exc, NetBoxAPIError):
        et = _api_error_type(exc.status_code)
        details: dict[str, Any] = {}
        if et is ErrorType.SERVER:
            details = {"body_excerpt": exc.body_snippet, "retry_safe": False}
        elif et is ErrorType.AUTH:
            details = {"reason": "rejected"}
        elif et is ErrorType.VALIDATION:
            details = {"source": "server", "body_excerpt": exc.body_snippet}
        return ErrorEnvelope(
            error=str(exc),
            type=et,
            endpoint=exc.url,
            status_code=exc.status_code,
            attempt_n=attempt_n,
            audit_log_path=_audit_log_path(),
            operation_id=operation_id,
            details=details,
        )
    if isinstance(exc, NetBoxClientError):
        return ErrorEnvelope(
            error=str(exc),
            type=ErrorType.TRANSPORT,
            endpoint=exc.url,
            attempt_n=attempt_n,
            audit_log_path=_audit_log_path(),
            operation_id=operation_id,
            details={"cause": "connect", "retry_safe": True},
        )
    if isinstance(exc, BranchError):
        return _branch_envelope(exc)
    if isinstance(exc, (NoProfileError, UnknownProfileError, KeyringStoreError)):
        return ErrorEnvelope(error=str(exc), type=ErrorType.CONFIG)
    return ErrorEnvelope(
        error=f"internal error: {exc}",
        type=ErrorType.INTERNAL,
        details={"traceback_id": str(uuid.uuid4())},
    )


def _branch_envelope(exc: BranchError) -> ErrorEnvelope:
    details: dict[str, Any] = {}
    if exc.branch is not None:
        details["branch"] = exc.branch
    et = ErrorType.CONFIG
    if isinstance(exc, BranchNotFoundError):
        et = ErrorType.NOT_FOUND
    elif isinstance(exc, BranchAmbiguousError):
        et = ErrorType.INPUT_ERROR
    elif isinstance(exc, BranchConflictError):
        et = ErrorType.CONFLICT
        details["conflicts"] = exc.conflicts
    elif isinstance(exc, BranchJobFailedError):
        et = ErrorType.VALIDATION
        details["job_id"] = exc.job_id
        details["job_error"] = exc.job_error
    elif isinstance(exc, BranchJobTimeoutError):
        et = ErrorType.TRANSPORT
        details["job_id"] = exc.job_id
    elif isinstance(exc, BranchNotReadyError):
        details["status"] = exc.status
    return ErrorEnvelope(error=str(exc), type=et, details=details)


def emit_envelope(env: ErrorEnvelope, *, output_format: OutputFormat, color: bool = False) -> int:
    """Write the envelope to the right target and return the exit code."""
    target = select_render_target(output_format=output_format, stdout_is_tty=sys.stdout.isatty())
    if target is RenderTarget.JSON_STDOUT:
        print(render_to_json(env), file=sys.stdout)
    elif target is RenderTarget.JSON_STDERR:
        print(render_to_json(env), file=sys.stderr)
    else:
        render_to_rich_stderr(env, stream=sys.stderr, color=color)
    return EXIT_CODES.get(env.type, 1)
