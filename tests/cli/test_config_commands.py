"""Smoke tests for the `nsc config` subcommand group.

The tests use Typer's `CliRunner` against an isolated `~/.nsc/` rooted at
`tmp_path`. They exercise the registration shape only; deeper behavior is
already covered by the writer-level unit tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nsc.cli.app import app


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Force `default_paths()` to root inside `tmp_path`."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NSC_HOME", str(tmp_path / ".nsc"))
    (tmp_path / ".nsc").mkdir()
    return tmp_path / ".nsc"


def _seed(home: Path, body: str) -> None:
    (home / "config.yaml").write_text(body, encoding="utf-8")


def test_config_path_prints_resolved_path(home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["config", "path"])
    assert result.exit_code == 0
    assert str(home / "config.yaml") in result.stdout


def test_config_get_returns_leaf_scalar(home: Path) -> None:
    _seed(
        home,
        "default_profile: prod\nprofiles:\n  prod:\n    url: https://nb.example/\n",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["config", "get", "default_profile"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "prod"


def test_config_get_returns_subtree_as_yaml(home: Path) -> None:
    _seed(
        home,
        "profiles:\n  prod:\n    url: https://nb.example/\n    token: secret\n",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["config", "get", "profiles.prod"])
    assert result.exit_code == 0
    assert "url: https://nb.example/" in result.stdout
    assert "token: secret" in result.stdout


def test_config_get_unknown_key_exits_nonzero(home: Path) -> None:
    _seed(home, "default_profile: prod\n")
    runner = CliRunner()
    result = runner.invoke(app, ["config", "get", "no.such.key"])
    assert result.exit_code != 0


def test_config_list_prints_full_doc(home: Path) -> None:
    _seed(home, "default_profile: prod\n")
    runner = CliRunner()
    result = runner.invoke(app, ["config", "list"])
    assert result.exit_code == 0
    assert "default_profile: prod" in result.stdout


def test_config_set_creates_file_when_missing(home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["config", "set", "default_profile", "prod"])
    assert result.exit_code == 0
    body = (home / "config.yaml").read_text(encoding="utf-8")
    assert "default_profile: prod" in body


def test_config_set_round_trips_existing_comments(home: Path) -> None:
    _seed(
        home,
        "# top comment\ndefault_profile: prod  # inline\n",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["config", "set", "defaults.page_size", "100"])
    assert result.exit_code == 0
    body = (home / "config.yaml").read_text(encoding="utf-8")
    assert "# top comment" in body
    assert "# inline" in body
    assert "page_size: '100'" in body or "page_size: 100" in body


def test_config_set_creates_intermediate_maps(home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["config", "set", "profiles.prod.url", "https://nb/"])
    assert result.exit_code == 0
    body = (home / "config.yaml").read_text(encoding="utf-8")
    assert "profiles:" in body
    assert "prod:" in body
    assert "url: https://nb/" in body


def test_config_unset_removes_leaf_and_prunes(home: Path) -> None:
    _seed(home, "defaults:\n  page_size: 50\n")
    runner = CliRunner()
    result = runner.invoke(app, ["config", "unset", "defaults.page_size"])
    assert result.exit_code == 0
    body = (home / "config.yaml").read_text(encoding="utf-8")
    assert "page_size" not in body
    assert "defaults" not in body


def test_config_set_refuses_map_to_scalar(home: Path) -> None:
    _seed(home, "profiles:\n  prod:\n    url: https://x/\n")
    runner = CliRunner()
    result = runner.invoke(app, ["config", "set", "profiles", "scalar"])
    assert result.exit_code != 0
    assert "map" in result.stdout + result.stderr


def test_config_edit_invokes_editor_via_env(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`nsc config edit` invokes $EDITOR with the config path."""
    captured: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool) -> None:
        captured.append(cmd)

    monkeypatch.setenv("EDITOR", "/usr/bin/true")
    monkeypatch.setattr("nsc.cli.config_commands.subprocess.run", fake_run)
    runner = CliRunner()
    result = runner.invoke(app, ["config", "edit"])
    assert result.exit_code == 0, result.stdout
    assert captured, "subprocess.run was not called"
    assert captured[0][0] == "/usr/bin/true"
    assert captured[0][1] == str(home / "config.yaml")
