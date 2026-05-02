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
