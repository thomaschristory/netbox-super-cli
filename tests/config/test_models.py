from __future__ import annotations

import pytest
from pydantic import ValidationError

from nsc.config.models import ColorMode, Config, Defaults, OutputFormat, Profile, SchemaRefresh


def test_defaults_have_sensible_values() -> None:
    d = Defaults()
    assert d.output is OutputFormat.TABLE
    assert d.page_size == 50
    assert d.timeout == 30.0
    assert d.schema_refresh is SchemaRefresh.DAILY


def test_profile_minimum_fields() -> None:
    p = Profile(name="prod", url="https://nb.example/")
    assert p.name == "prod"
    assert p.token is None
    assert p.verify_ssl is True
    assert p.schema_url is None
    assert p.timeout is None


def test_profile_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Profile(name="prod", url="https://nb.example/", bogus="x")


def test_config_empty_defaults() -> None:
    c = Config()
    assert c.default_profile is None
    assert c.profiles == {}
    assert c.defaults == Defaults()
    assert c.columns == {}


def test_config_holds_columns_per_tag_and_resource() -> None:
    c = Config(columns={"dcim": {"devices": ["id", "name", "site"]}})
    assert c.columns["dcim"]["devices"] == ["id", "name", "site"]


def test_output_format_values() -> None:
    assert {f.value for f in OutputFormat} == {"table", "json", "jsonl", "yaml", "csv"}


def test_defaults_color_mode_is_auto() -> None:
    d = Defaults()
    assert d.color_mode is ColorMode.AUTO


def test_color_mode_values() -> None:
    assert {m.value for m in ColorMode} == {"auto", "on", "off"}
