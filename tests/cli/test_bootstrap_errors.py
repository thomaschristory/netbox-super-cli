"""Bootstrap failures surface as usage errors for every command (#186)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nsc.cli.app import app

_STATIC = [["ls", "sites"], ["get", "sites", "1"], ["branch", "list"], ["tui"]]


@pytest.fixture(autouse=True)
def _empty_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("NSC_HOME", str(tmp_path))
    for var in ("NSC_URL", "NSC_TOKEN", "NSC_PROFILE", "NSC_SCHEMA", "NSC_OUTPUT", "NSC_BRANCH"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def _combined(result: object) -> str:
    text = (result.stdout or "") + (result.stderr or "")  # type: ignore[attr-defined]
    # CI forces color and Rich wraps the error panel; compare on plain, unwrapped text.
    plain = re.sub(r"\x1b\[[0-9;]*m", "", text)
    return " ".join(plain.replace("│", " ").split())


def _assert_usage_error(result: object, *needles: str) -> None:
    text = _combined(result)
    assert result.exit_code == 2, (result.exit_code, text)  # type: ignore[attr-defined]
    assert "internal" not in text
    assert "Traceback" not in text
    for needle in needles:
        assert needle in text, (needle, text)


@pytest.mark.parametrize("command", [*_STATIC, ["dcim", "sites", "list"]])
def test_no_profile_is_reported_for_every_command(command: list[str]) -> None:
    _assert_usage_error(CliRunner().invoke(app, command), "no NetBox URL")


@pytest.mark.parametrize("command", _STATIC)
def test_unknown_profile_is_reported_for_static_commands(command: list[str]) -> None:
    _assert_usage_error(CliRunner().invoke(app, ["--profile", "nope", *command]), "nope")


@pytest.mark.parametrize("command", [*_STATIC, ["dcim", "sites", "list"]])
@pytest.mark.parametrize("url", ["not-a-url", "http://", "ftp://nb.example"])
def test_invalid_url_flag_is_usage_error(command: list[str], url: str) -> None:
    result = CliRunner().invoke(app, ["--url", url, "--token", "t", *command])
    _assert_usage_error(result, "invalid NetBox URL", url, "--url")


def test_invalid_url_env_is_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NSC_URL", "not-a-url")
    monkeypatch.setenv("NSC_TOKEN", "t")
    _assert_usage_error(CliRunner().invoke(app, ["dcim", "sites", "list"]), "NSC_URL")


def test_invalid_schema_url_is_usage_error() -> None:
    result = CliRunner().invoke(
        app, ["--url", "https://nb.example", "--token", "t", "--schema", "http://", "ls", "x"]
    )
    _assert_usage_error(result, "invalid", "--schema")


def test_static_command_help_still_works_without_profile() -> None:
    result = CliRunner().invoke(app, ["ls", "--help"])
    assert result.exit_code == 0, _combined(result)
    assert "Usage" in result.stdout
