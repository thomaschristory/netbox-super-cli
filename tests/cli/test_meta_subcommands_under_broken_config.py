"""Regression tests for issue #10.

A malformed `~/.nsc/config.yaml` must not block meta subcommands. Before this
patch, the `ConfigParseError` recovery branch in `nsc/cli/app.py:_root` listed
only 5 of the 7 meta subcommands — `commands` and `config` were missing, so
running them against a broken YAML failed with the unhelpful root-level
`ConfigParseError` instead of recovering and dispatching to the handler.

The fix sources the recovery set from `_META_COMMANDS` directly, eliminating
the second source of truth.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nsc.cli.app import app


def _bundled_schema() -> Path:
    bundled = Path(__file__).resolve().parents[2] / "nsc" / "schemas" / "bundled"
    candidates = sorted(bundled.glob("netbox-*.json.gz"))
    assert candidates
    return candidates[-1]


@pytest.fixture
def broken_config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".nsc"
    home.mkdir()
    (home / "config.yaml").write_text(": : : not valid yaml :\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NSC_HOME", str(home))
    monkeypatch.delenv("NSC_PROFILE", raising=False)
    monkeypatch.delenv("NSC_URL", raising=False)
    monkeypatch.delenv("NSC_TOKEN", raising=False)
    return home


def test_commands_runs_with_broken_config(broken_config_home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app, ["commands", "--output", "json", "--schema", str(_bundled_schema())]
    )
    assert result.exit_code == 0, result.stderr
    json.loads(result.stdout)


def test_config_path_runs_with_broken_config(broken_config_home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["config", "path"])
    assert result.exit_code == 0, result.stderr
    assert str(broken_config_home / "config.yaml") in result.stdout


def test_cache_prune_runs_with_broken_config(broken_config_home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["cache", "prune"])
    assert result.exit_code == 0, result.stderr


def test_skill_install_dry_run_runs_with_broken_config(broken_config_home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["skill", "install", "--target", "codex"])
    assert result.exit_code == 0, result.stderr


@pytest.mark.parametrize(
    "argv",
    [
        ["init"],
        ["login"],
        ["profiles", "list"],
    ],
)
def test_root_does_not_emit_config_parse_error_for_meta(
    argv: list[str], broken_config_home: Path
) -> None:
    """These meta subcommands re-load the config inside their own handlers, so
    they may exit non-zero against a broken config — but they must do so via
    their own structured envelope, not the root-level `Error: <ConfigParseError>`
    message #10 is fixing.
    """
    runner = CliRunner()
    result = runner.invoke(app, argv, input="")
    assert "Error: " not in (result.stderr or ""), (
        f"`nsc {' '.join(argv)}` surfaced the root-level config-parse error "
        f"instead of recovering: {result.stderr!r}"
    )
