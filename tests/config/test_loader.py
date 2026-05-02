from __future__ import annotations

from pathlib import Path

import pytest

from nsc.config import Config, OutputFormat
from nsc.config.loader import ConfigParseError, load_config


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_missing_file_returns_empty_config(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "does-not-exist.yaml")
    assert isinstance(cfg, Config)
    assert cfg.profiles == {}
    assert cfg.default_profile is None


def test_loads_minimal_profile(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        default_profile: prod
        profiles:
          prod:
            url: https://netbox.example.com
            token: secret
        """,
    )
    cfg = load_config(path)
    assert cfg.default_profile == "prod"
    assert "prod" in cfg.profiles
    assert str(cfg.profiles["prod"].url).rstrip("/") == "https://netbox.example.com"
    assert cfg.profiles["prod"].token == "secret"


def test_env_constructor_substitutes_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NSC_TEST_TOKEN", "abc123")
    path = _write(
        tmp_path,
        """
        profiles:
          prod:
            url: https://nb.example/
            token: !env NSC_TEST_TOKEN
        """,
    )
    cfg = load_config(path)
    assert cfg.profiles["prod"].token == "abc123"


def test_env_constructor_returns_none_when_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NSC_TEST_MISSING", raising=False)
    path = _write(
        tmp_path,
        """
        profiles:
          prod:
            url: https://nb.example/
            token: !env NSC_TEST_MISSING
        """,
    )
    cfg = load_config(path)
    assert cfg.profiles["prod"].token is None


def test_env_constructor_with_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NSC_TEST_FALLBACK", raising=False)
    path = _write(
        tmp_path,
        """
        profiles:
          prod:
            url: https://nb.example/
            token: !env NSC_TEST_FALLBACK fallback-value
        """,
    )
    cfg = load_config(path)
    assert cfg.profiles["prod"].token == "fallback-value"


def test_malformed_yaml_raises_config_parse_error(tmp_path: Path) -> None:
    path = _write(tmp_path, "profiles: {{{")
    with pytest.raises(ConfigParseError):
        load_config(path)


def test_columns_are_loaded(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        profiles:
          prod:
            url: https://nb.example/
            token: x
        columns:
          dcim:
            devices: [id, name, site]
        """,
    )
    cfg = load_config(path)
    assert cfg.columns["dcim"]["devices"] == ["id", "name", "site"]


def test_defaults_section_overrides(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        defaults:
          output: json
          page_size: 200
          timeout: 60
        """,
    )
    cfg = load_config(path)
    assert cfg.defaults.output is OutputFormat.JSON
    assert cfg.defaults.page_size == 200
    assert cfg.defaults.timeout == 60.0


def test_loader_preserves_comments_through_round_trip(tmp_path: Path) -> None:
    """A read followed by a write of the same doc preserves comments.

    This is a foundational guarantee for `nsc config set/unset` (Phase 4a).
    Phase 4a's loader uses ruamel.yaml's round-trip mode; this asserts a
    parsed doc still carries comments when re-emitted.
    """
    from nsc.config.writer import dump_round_trip, load_round_trip  # noqa: PLC0415

    body = (
        "# top comment\n"
        "default_profile: prod  # default\n"
        "profiles:\n"
        "  prod:\n"
        "    url: https://nb.example/\n"
        "    token: secret  # inline comment\n"
    )
    path = _write(tmp_path, body)

    doc = load_round_trip(path)
    out = dump_round_trip(doc)

    assert "# top comment" in out
    assert "# default" in out
    assert "# inline comment" in out
