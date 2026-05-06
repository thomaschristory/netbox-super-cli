from __future__ import annotations

from typing import Any

import pytest

from nsc.cache.store import _PROFILE_RE
from nsc.cli.runtime import (
    CLIOverrides,
    NoProfileError,
    ResolvedProfile,
    UnknownProfileError,
    resolve_profile,
    resolve_transport_settings,
)
from nsc.config.models import Config, Defaults, Profile


def _cfg(**kwargs: Any) -> Config:
    return Config(**kwargs)


def test_flag_url_and_token_with_no_profile_makes_adhoc() -> None:
    cfg = _cfg()
    overrides = CLIOverrides(url="https://nb.example", token="tok")
    rp = resolve_profile(cfg, overrides, env={})
    assert isinstance(rp, ResolvedProfile)
    assert rp.name == "adhoc"
    assert str(rp.url).rstrip("/") == "https://nb.example"
    assert rp.token == "tok"
    assert rp.verify_ssl is True
    assert rp.timeout == Defaults().timeout


def test_env_url_and_token_with_no_profile_makes_adhoc() -> None:
    cfg = _cfg()
    rp = resolve_profile(
        cfg, CLIOverrides(), env={"NSC_URL": "https://nb.example", "NSC_TOKEN": "envtok"}
    )
    assert rp.name == "adhoc"
    assert rp.token == "envtok"


def test_adhoc_sentinel_is_a_valid_cache_profile_name() -> None:
    # Regression: the sentinel returned by _select_base_profile() ends up as
    # a cache subdirectory name and must satisfy nsc.cache.store._PROFILE_RE,
    # otherwise every env-var-only invocation explodes the moment the schema
    # cache is touched.
    cfg = _cfg()
    rp = resolve_profile(
        cfg, CLIOverrides(), env={"NSC_URL": "https://nb.example", "NSC_TOKEN": "t"}
    )
    assert _PROFILE_RE.match(rp.name) is not None, rp.name


def test_default_profile_is_chosen_when_no_overrides() -> None:
    cfg = _cfg(
        default_profile="prod",
        profiles={
            "prod": Profile(name="prod", url="https://prod.example", token="ptok"),
            "lab": Profile(name="lab", url="https://lab.example", token="ltok"),
        },
    )
    rp = resolve_profile(cfg, CLIOverrides(), env={})
    assert rp.name == "prod"
    assert rp.token == "ptok"


def test_profile_flag_overrides_default_profile() -> None:
    cfg = _cfg(
        default_profile="prod",
        profiles={
            "prod": Profile(name="prod", url="https://prod.example", token="ptok"),
            "lab": Profile(name="lab", url="https://lab.example", token="ltok"),
        },
    )
    rp = resolve_profile(cfg, CLIOverrides(profile="lab"), env={})
    assert rp.name == "lab"
    assert rp.token == "ltok"


def test_env_nsc_profile_overrides_default() -> None:
    cfg = _cfg(
        default_profile="prod",
        profiles={
            "prod": Profile(name="prod", url="https://prod.example", token="ptok"),
            "lab": Profile(name="lab", url="https://lab.example", token="ltok"),
        },
    )
    rp = resolve_profile(cfg, CLIOverrides(), env={"NSC_PROFILE": "lab"})
    assert rp.name == "lab"


def test_flag_token_overrides_profile_token() -> None:
    cfg = _cfg(profiles={"prod": Profile(name="prod", url="https://prod.example", token="ptok")})
    rp = resolve_profile(
        cfg, CLIOverrides(profile="prod", token="OVERRIDE"), env={"NSC_TOKEN": "envtok"}
    )
    assert rp.token == "OVERRIDE"


def test_env_token_beats_yaml_token_but_loses_to_flag() -> None:
    cfg = _cfg(profiles={"prod": Profile(name="prod", url="https://prod.example", token="ptok")})
    rp = resolve_profile(cfg, CLIOverrides(profile="prod"), env={"NSC_TOKEN": "envtok"})
    assert rp.token == "envtok"


def test_unknown_profile_raises() -> None:
    cfg = _cfg(profiles={"prod": Profile(name="prod", url="https://prod.example", token="ptok")})
    with pytest.raises(UnknownProfileError):
        resolve_profile(cfg, CLIOverrides(profile="nope"), env={})


def test_no_url_or_token_anywhere_raises_no_profile_error() -> None:
    cfg = _cfg()
    with pytest.raises(NoProfileError):
        resolve_profile(cfg, CLIOverrides(), env={})


def test_profile_with_unset_token_and_flag_token_succeeds() -> None:
    cfg = _cfg(profiles={"prod": Profile(name="prod", url="https://prod.example", token=None)})
    rp = resolve_profile(cfg, CLIOverrides(profile="prod", token="flagtok"), env={})
    assert rp.token == "flagtok"


def test_insecure_flag_disables_verify_ssl() -> None:
    cfg = _cfg()
    rp = resolve_profile(
        cfg,
        CLIOverrides(url="https://nb.example", token="tok", insecure=True),
        env={},
    )
    assert rp.verify_ssl is False


def test_schema_url_overrides_chain() -> None:
    cfg = _cfg(
        profiles={
            "prod": Profile(
                name="prod",
                url="https://prod.example",
                token="t",
                schema_url="https://prod.example/api/schema/?format=json",
            )
        },
        default_profile="prod",
    )
    rp = resolve_profile(cfg, CLIOverrides(), env={})
    assert str(rp.schema_url) == "https://prod.example/api/schema/?format=json"

    rp2 = resolve_profile(
        cfg, CLIOverrides(schema_override="https://other.example/schema.json"), env={}
    )
    assert str(rp2.schema_url) == "https://other.example/schema.json"


def test_resolve_transport_settings_default() -> None:
    verify_ssl, timeout = resolve_transport_settings(_cfg(), CLIOverrides(), env={})
    assert verify_ssl is True
    assert timeout == Defaults().timeout


def test_resolve_transport_settings_insecure_flag_disables_verify() -> None:
    verify_ssl, _ = resolve_transport_settings(_cfg(), CLIOverrides(insecure=True), env={})
    assert verify_ssl is False


def test_resolve_transport_settings_no_insecure_flag_forces_verify() -> None:
    cfg = _cfg(
        profiles={
            "prod": Profile(name="prod", url="https://nb.example", token="t", verify_ssl=False)
        },
        default_profile="prod",
    )
    verify_ssl, _ = resolve_transport_settings(cfg, CLIOverrides(insecure=False), env={})
    assert verify_ssl is True


def test_resolve_transport_settings_env_var_disables_verify() -> None:
    verify_ssl, _ = resolve_transport_settings(_cfg(), CLIOverrides(), env={"NSC_INSECURE": "1"})
    assert verify_ssl is False


def test_resolve_transport_settings_falls_back_to_profile_verify_ssl() -> None:
    cfg = _cfg(
        profiles={
            "prod": Profile(name="prod", url="https://nb.example", token="t", verify_ssl=False)
        },
        default_profile="prod",
    )
    verify_ssl, _ = resolve_transport_settings(cfg, CLIOverrides(), env={})
    assert verify_ssl is False


def test_resolve_transport_settings_uses_profile_timeout() -> None:
    cfg = _cfg(
        profiles={"prod": Profile(name="prod", url="https://nb.example", token="t", timeout=7.5)},
        default_profile="prod",
    )
    _, timeout = resolve_transport_settings(cfg, CLIOverrides(), env={})
    assert timeout == 7.5
