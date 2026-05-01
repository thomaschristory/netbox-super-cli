"""Runtime context, profile resolution, exit-code mapping.

`RuntimeContext` itself (carrying the live `NetBoxClient`) is completed in the
bootstrap wiring task. This module owns the data classes and the resolution
function, both consumed by the bootstrap.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, HttpUrl

from nsc.config.models import Config, Profile


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class CLIOverrides(_Frozen):
    profile: str | None = None
    url: str | None = None
    token: str | None = None
    insecure: bool | None = None
    schema: str | None = None  # type: ignore[assignment]
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
        overrides.schema,
        env.get("NSC_SCHEMA"),
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
        return None, "<adhoc>"
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
