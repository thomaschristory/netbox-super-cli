"""Runtime context, profile resolution, exit-code mapping.

`RuntimeContext` carries the live `NetBoxClient`, command model, config, and
output preferences for a single invocation. It is populated by the bootstrap
pipeline in the root Typer callback (Task 12) and consumed by the dynamic
read handlers.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterable, Iterator, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, HttpUrl, SkipValidation

from nsc.cache.store import ADHOC_PROFILE
from nsc.config.models import ColorMode, Config, OutputFormat, Profile
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


def resolve_profile(
    config: Config,
    overrides: CLIOverrides,
    env: Mapping[str, str],
) -> ResolvedProfile:
    base, base_name = _select_base_profile(config, overrides, env)

    url = _first_set(overrides.url, env.get("NSC_URL"), str(base.url) if base else None)
    token = _first_set(overrides.token, env.get("NSC_TOKEN"), base.token if base else None)
    if url is None or token is None:
        raise NoProfileError(
            "no NetBox URL/token configured (set NSC_URL+NSC_TOKEN, "
            "pass --url and --token, or configure a profile in ~/.nsc/config.yaml)"
        )

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

    schema_url_raw = _first_set(
        _url_only(overrides.schema_override),
        _url_only(env.get("NSC_SCHEMA")),
        str(base.schema_url) if base and base.schema_url else None,
    )

    return ResolvedProfile(
        name=base_name,
        url=HttpUrl(url),
        token=token,
        verify_ssl=verify_ssl,
        timeout=timeout,
        schema_url=HttpUrl(schema_url_raw) if schema_url_raw else None,
    )


def _select_base_profile(
    config: Config, overrides: CLIOverrides, env: Mapping[str, str]
) -> tuple[Profile | None, str]:
    name = overrides.profile or env.get("NSC_PROFILE") or config.default_profile
    if name is None:
        return None, ADHOC_PROFILE
    if name not in config.profiles:
        raise UnknownProfileError(f"profile {name!r} is not defined in ~/.nsc/config.yaml")
    return config.profiles[name], name


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
    schema_override flow consumes the raw value directly from `CLIOverrides`.
    """
    if value is None or not value:
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


class RuntimeContext(BaseModel):
    """Per-invocation runtime state.

    Not frozen because `client` (a NetBoxClient wrapping httpx.Client) is mutable.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    resolved_profile: ResolvedProfile
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
    apply: bool = False
    explain: bool = False
    strict: bool = False
    file: str | None = None
    fields: list[str] = []
    file_format: str | None = None
    bulk: bool | None = None
    no_bulk: bool | None = None
    on_error: Literal["stop", "continue"] = "stop"

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
        cap = limit
    elif fetch_all:
        cap = None
    else:
        cap = page_size
    for n, record in enumerate(iterator):
        if cap is not None and n >= cap:
            return
        yield record


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
) -> ErrorEnvelope:
    """Translate a known nsc exception into an ErrorEnvelope. Unknown → internal."""
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
    if isinstance(exc, NoProfileError):
        return ErrorEnvelope(error=str(exc), type=ErrorType.CONFIG)
    if isinstance(exc, UnknownProfileError):
        return ErrorEnvelope(error=str(exc), type=ErrorType.CONFIG)
    return ErrorEnvelope(
        error=f"internal error: {exc}",
        type=ErrorType.INTERNAL,
        details={"traceback_id": str(uuid.uuid4())},
    )


def emit_envelope(env: ErrorEnvelope, *, output_format: OutputFormat, color: bool = False) -> int:
    """Write the envelope to the right target and return the exit code."""
    target = select_render_target(output_format=output_format, stdout_is_tty=sys.stdout.isatty())
    if target is RenderTarget.JSON_STDOUT:
        print(render_to_json(env), file=sys.stdout)
    elif target is RenderTarget.JSON_STDERR:
        print(render_to_json(env), file=sys.stderr)
    else:
        render_to_rich_stderr(env, stream=sys.stderr)
    return EXIT_CODES.get(env.type, 1)
