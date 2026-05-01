"""Smoke tests that prove the Typer entry point is wired up."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nsc._version import __version__
from nsc.cli.app import app


def test_version_flag_prints_version() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_no_args_shows_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, [])
    assert result.exit_code == 2
    assert "netbox-super-cli" in result.stdout


def test_no_profile_anywhere_gives_helpful_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NSC_HOME", str(tmp_path))
    for var in ("NSC_URL", "NSC_TOKEN", "NSC_PROFILE", "NSC_SCHEMA"):
        monkeypatch.delenv(var, raising=False)
    result = CliRunner().invoke(app, ["dcim", "devices", "list"])
    assert result.exit_code == 2
    combined = (result.stdout or "") + (result.stderr or "")
    assert "no NetBox URL" in combined


def test_meta_command_commands_still_works_with_explicit_schema(tmp_path: Path) -> None:
    schema = tmp_path / "s.json"
    schema.write_text(
        '{"openapi":"3.0.3","info":{"title":"t","version":"1.0.0"},'
        '"paths":{},"tags":[],"components":{"schemas":{}}}',
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["commands", "--schema", str(schema), "--output", "json"])
    assert result.exit_code == 0
    assert '"tags"' in result.stdout
