"""`nsc login` — verify / create / rotate a profile's token.

Three modes (mutually exclusive):

* bare or `--profile <name>` — verify an existing profile against the live NetBox.
* `--new --profile <name>` — create a new profile entry, then verify.
* `--rotate --profile <name>` — prompt for a new token, verify, replace in storage.

`--store keyring` puts the token in the OS keyring and writes only a
`!keyring NAME` reference to the config file; the plaintext never touches disk.

All three end with `verify()`; only success persists changes (for `--rotate`)
or returns 0 (for bare). Cache is never touched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from ruamel.yaml.comments import CommentedMap, TaggedScalar

from nsc.auth.keyring_store import KeyringStoreError, resolve_token, set_secret
from nsc.auth.verify import VerifyError, describe_identity, verify
from nsc.cli.runtime import ResolvedProfile, emit_envelope
from nsc.config.loader import ConfigParseError, load_config
from nsc.config.models import KeyringRef, OutputFormat, Profile
from nsc.config.settings import default_paths
from nsc.config.writer import (
    acquire_lock,
    atomic_write,
    dump_round_trip,
    load_round_trip,
)
from nsc.output.errors import ErrorEnvelope, ErrorType
from nsc.schema.source import resolve_command_model


def _config_path() -> Path:
    return default_paths().config_file


_STORE_PLAINTEXT = "plaintext"
_STORE_ENV = "env"
_STORE_KEYRING = "keyring"
_STORES = (_STORE_PLAINTEXT, _STORE_ENV, _STORE_KEYRING)


def _env_tagged(var_name: str) -> object:
    """Build a `!env <VARNAME>` scalar that ruamel will emit with its tag intact."""
    return TaggedScalar(value=var_name, style=None, tag="!env")


def _keyring_tagged(name: str) -> object:
    """Build a `!keyring <NAME>` scalar that ruamel will emit with its tag intact."""
    return TaggedScalar(value=name, style=None, tag="!keyring")


def _normalize_store(store: str | None, *, default: str) -> str:
    # Reject unknown values: silently falling back to plaintext on a typo such
    # as `--store keyrnig` would write the secret to disk.
    value = (store or default).strip().lower()
    if value not in _STORES:
        raise typer.BadParameter(f"--store must be one of: {', '.join(_STORES)}")
    return value


def _normalize_keyring_name(name: str | None) -> str | None:
    # The loader strips `!keyring` values and rejects empty ones, so the writer
    # must agree or the stored secret is unreachable / the config unloadable.
    if name is None:
        return None
    value = name.strip()
    if not value:
        raise typer.BadParameter("--keyring-name must not be empty")
    return value


def _store_token(
    store: str,
    *,
    token: str,
    env_var: str | None,
    keyring_name: str,
) -> object:
    """Persist `token` per `store` and return the config value referencing it."""
    if store == _STORE_ENV:
        if not env_var:
            raise typer.BadParameter("--store=env requires --env-var <NAME>")
        return _env_tagged(env_var)
    if store == _STORE_KEYRING:
        try:
            set_secret(keyring_name, token)
        except KeyringStoreError as exc:
            code = _emit_keyring_envelope(exc)
            raise typer.Exit(code=code) from exc
        return _keyring_tagged(keyring_name)
    return token


def _emit_auth_envelope(
    message: str,
    *,
    status_code: int | None,
    user_check_status: int | None,
) -> int:
    details: dict[str, object] = {"reason": "rejected"}
    if user_check_status is not None:
        details["user_check_status"] = user_check_status
    env = ErrorEnvelope(
        error=message,
        type=ErrorType.AUTH,
        status_code=status_code,
        details=details,
    )
    return emit_envelope(env, output_format=OutputFormat.TABLE)


def _emit_config_envelope(message: str) -> int:
    env = ErrorEnvelope(error=message, type=ErrorType.CONFIG)
    return emit_envelope(env, output_format=OutputFormat.TABLE)


def _emit_keyring_envelope(exc: KeyringStoreError) -> int:
    env = ErrorEnvelope(
        error=str(exc),
        type=ErrorType.CONFIG,
        details={"keyring_name": exc.keyring_name},
    )
    return emit_envelope(env, output_format=OutputFormat.TABLE)


def _resolved_profile(name: str) -> Profile:
    """Return the validated `Profile` for `name`, raising on missing/invalid config."""
    try:
        config = load_config(_config_path())
    except ConfigParseError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if name not in config.profiles:
        raise typer.BadParameter(f"profile {name!r} not in config")
    return config.profiles[name]


def _ensure_profile_exists_in_doc(doc: CommentedMap, name: str) -> CommentedMap:
    profiles = doc.get("profiles")
    if not isinstance(profiles, CommentedMap):
        profiles = CommentedMap()
        doc["profiles"] = profiles
    if name not in profiles:
        profiles[name] = CommentedMap()
    entry = profiles[name]
    assert isinstance(entry, CommentedMap)
    return entry


def _write_profile_entry(*, profile: str, url: str, token_value: object, set_default: bool) -> None:
    path = _config_path()
    with acquire_lock(path):
        doc = load_round_trip(path)
        if set_default and "default_profile" not in doc:
            doc["default_profile"] = profile
        entry = _ensure_profile_exists_in_doc(doc, profile)
        entry["url"] = url
        entry["token"] = token_value
        atomic_write(path, dump_round_trip(doc))


def _replace_token(profile: str, token_value: object) -> None:
    path = _config_path()
    with acquire_lock(path):
        doc = load_round_trip(path)
        profiles = doc.get("profiles")
        if not isinstance(profiles, CommentedMap) or profile not in profiles:
            raise typer.BadParameter(f"profile {profile!r} not in config")
        entry = profiles[profile]
        if not isinstance(entry, CommentedMap):
            raise typer.BadParameter(f"profile {profile!r} is not a mapping")
        entry["token"] = token_value
        atomic_write(path, dump_round_trip(doc))


def _print_success(username: str | None, version: str) -> None:
    typer.echo(f"✓ {describe_identity(username)}, NetBox {version}")


def _fetch_schema_for_login(profile: Profile, token: str) -> None:
    rp = ResolvedProfile(
        name=profile.name,
        url=profile.url,
        token=token,
        verify_ssl=profile.verify_ssl,
        timeout=profile.timeout if profile.timeout is not None else 30.0,
        schema_url=profile.schema_url,
    )
    schema_url = (
        str(rp.schema_url)
        if rp.schema_url is not None
        else f"{str(rp.url).rstrip('/')}/api/schema/?format=json"
    )
    typer.echo(f"Fetching schema from {schema_url} ...")
    try:
        resolve_command_model(
            paths=default_paths(),
            profile=rp,
            schema_override=None,
            force_refresh=True,
        )
        typer.echo("Schema cached.")
    except Exception as exc:
        typer.echo(f"Warning: schema fetch failed ({exc}); skipping.", err=True)


def register(app: typer.Typer) -> None:
    @app.command("login", help="Verify / create / rotate a profile's token.")
    def login_cmd(
        profile: Annotated[str | None, typer.Option("--profile")] = None,
        new: Annotated[bool, typer.Option("--new", help="Create a new profile.")] = False,
        rotate: Annotated[
            bool, typer.Option("--rotate", help="Replace an existing profile's token.")
        ] = False,
        url: Annotated[str | None, typer.Option("--url")] = None,
        store: Annotated[
            str | None,
            typer.Option(
                "--store",
                help=(
                    "Token storage: plaintext|env|keyring. Default: plaintext for --new; "
                    "--rotate keeps an existing !keyring reference, else plaintext."
                ),
            ),
        ] = None,
        env_var: Annotated[
            str | None,
            typer.Option(
                "--env-var",
                help="Environment variable name (required when --store=env).",
            ),
        ] = None,
        keyring_name: Annotated[
            str | None,
            typer.Option(
                "--keyring-name",
                help=(
                    "OS keyring entry name for --store=keyring (service 'nsc'). "
                    "Default: the existing !keyring name on --rotate, else the profile name."
                ),
            ),
        ] = None,
        fetch_schema: Annotated[
            bool,
            typer.Option(
                "--fetch-schema",
                help="Fetch and cache the live OpenAPI schema (applies to verify and --new).",
            ),
        ] = False,
    ) -> None:
        if new and rotate:
            raise typer.BadParameter("--new and --rotate are mutually exclusive")
        keyring_name = _normalize_keyring_name(keyring_name)

        if new:
            _do_login_new(
                profile,
                url,
                _normalize_store(store, default=_STORE_PLAINTEXT),
                env_var,
                keyring_name,
                fetch_schema=fetch_schema,
            )
            return
        if rotate:
            _do_login_rotate(profile, store, env_var, keyring_name)
            return
        _do_login_verify(profile, fetch_schema=fetch_schema)


def _do_login_verify(profile_name: str | None, *, fetch_schema: bool = False) -> None:
    try:
        config = load_config(_config_path())
    except ConfigParseError as exc:
        code = _emit_config_envelope(str(exc))
        raise typer.Exit(code=code) from exc
    name = profile_name or config.default_profile
    if name is None:
        code = _emit_config_envelope("no profile selected and no default_profile set in config")
        raise typer.Exit(code=code)
    if name not in config.profiles:
        code = _emit_config_envelope(f"profile {name!r} not in config")
        raise typer.Exit(code=code)
    try:
        token = resolve_token(config.profiles[name])
    except KeyringStoreError as exc:
        code = _emit_keyring_envelope(exc)
        raise typer.Exit(code=code) from exc
    profile = config.profiles[name].model_copy(update={"token": token})
    try:
        result = verify(profile)
    except VerifyError as exc:
        code = _emit_auth_envelope(
            str(exc),
            status_code=exc.status_code,
            user_check_status=exc.user_check_status,
        )
        raise typer.Exit(code=code) from exc
    _print_success(result.username, result.netbox_version)
    if fetch_schema:
        if token is None:
            typer.echo("Warning: token not available from config; skipping schema fetch.", err=True)
            return
        _fetch_schema_for_login(profile, token)


def _do_login_new(
    profile_name: str | None,
    url: str | None,
    store: str,
    env_var: str | None,
    keyring_name: str | None,
    *,
    fetch_schema: bool = False,
) -> None:
    if profile_name is None:
        raise typer.BadParameter("--new requires --profile <name>")
    if url is None:
        raise typer.BadParameter("--new requires --url <url>")
    try:
        existing_config = load_config(_config_path())
    except ConfigParseError:
        existing_config = None
    if existing_config and profile_name in existing_config.profiles:
        typer.echo(
            f"error: profile {profile_name!r} already exists; "
            f"use `nsc login --rotate --profile {profile_name}` to replace its token.",
            err=True,
        )
        raise typer.Exit(code=12)
    if store == _STORE_ENV and not env_var:
        raise typer.BadParameter("--store=env requires --env-var <NAME>")
    token_input = typer.prompt("Token", hide_input=True)
    token_for_verify = token_input.strip()

    candidate = Profile(name=profile_name, url=url, token=token_for_verify)  # type: ignore[arg-type]
    try:
        result = verify(candidate)
    except VerifyError as exc:
        code = _emit_auth_envelope(
            str(exc),
            status_code=exc.status_code,
            user_check_status=exc.user_check_status,
        )
        raise typer.Exit(code=code) from exc
    token_value = _store_token(
        store,
        token=token_for_verify,
        env_var=env_var,
        keyring_name=keyring_name or profile_name,
    )
    set_default = (existing_config is None) or (existing_config.default_profile is None)
    _write_profile_entry(
        profile=profile_name,
        url=url,
        token_value=token_value,
        set_default=set_default,
    )
    _print_success(result.username, result.netbox_version)
    if fetch_schema or typer.confirm("Fetch and cache the live schema now?", default=True):
        _fetch_schema_for_login(candidate, token_for_verify)


def _do_login_rotate(
    profile_name: str | None,
    store_option: str | None,
    env_var: str | None,
    keyring_name: str | None,
) -> None:
    if profile_name is None:
        raise typer.BadParameter("--rotate requires --profile <name>")
    profile = _resolved_profile(profile_name)
    existing_ref = profile.token if isinstance(profile.token, KeyringRef) else None
    store = _normalize_store(
        store_option,
        default=_STORE_KEYRING if existing_ref is not None else _STORE_PLAINTEXT,
    )
    if store == _STORE_ENV and not env_var:
        raise typer.BadParameter("--store=env requires --env-var <NAME>")
    new_token = typer.prompt("New token", hide_input=True).strip()

    candidate = Profile(
        name=profile.name,
        url=profile.url,
        token=new_token,
        verify_ssl=profile.verify_ssl,
        schema_url=profile.schema_url,
        timeout=profile.timeout,
    )
    try:
        result = verify(candidate)
    except VerifyError as exc:
        code = _emit_auth_envelope(
            str(exc),
            status_code=exc.status_code,
            user_check_status=exc.user_check_status,
        )
        raise typer.Exit(code=code) from exc

    token_value = _store_token(
        store,
        token=new_token,
        env_var=env_var,
        keyring_name=keyring_name or (existing_ref.name if existing_ref else profile_name),
    )
    _replace_token(profile_name, token_value)
    _print_success(result.username, result.netbox_version)
