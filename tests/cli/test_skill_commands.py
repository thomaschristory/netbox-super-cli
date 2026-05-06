"""Typer-level tests for `nsc skill install` (Phase 5c)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nsc.cli.app import app


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect $HOME to a tmp dir so per-target resolvers stay sandboxed."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_install_dry_run_claude_code_prints_would_write(home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["skill", "install", "--target", "claude-code"])

    assert result.exit_code == 0, result.output
    assert "would write to" in result.output
    assert "skills/netbox-super-cli/SKILL.md" in result.output
    assert not (home / ".claude" / "skills" / "netbox-super-cli" / "SKILL.md").exists()


def test_install_apply_claude_code_writes_file(home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["skill", "install", "--target", "claude-code", "--apply"])

    assert result.exit_code == 0, result.output
    dest = home / ".claude" / "skills" / "netbox-super-cli" / "SKILL.md"
    assert dest.exists()
    text = dest.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "name: netbox-super-cli" in text


def test_install_apply_codex_writes_to_agents_skills(home: Path) -> None:
    """Codex CLI loads from $HOME/.agents/skills/ (not ~/.codex/) per T1 research."""
    runner = CliRunner()
    result = runner.invoke(app, ["skill", "install", "--target", "codex", "--apply"])

    assert result.exit_code == 0, result.output
    dest = home / ".agents" / "skills" / "netbox-super-cli" / "SKILL.md"
    assert dest.exists()


def test_install_dry_run_gemini_prints_manual_instructions(home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["skill", "install", "--target", "gemini"])

    assert result.exit_code == 0, result.output
    assert "GEMINI.md" in result.output or "Gemini" in result.output
    assert "would write to" not in result.output


def test_install_apply_overwrites_existing_file(home: Path) -> None:
    runner = CliRunner()
    runner.invoke(app, ["skill", "install", "--target", "claude-code", "--apply"])
    dest = home / ".claude" / "skills" / "netbox-super-cli" / "SKILL.md"
    dest.write_text("stale content")

    result = runner.invoke(app, ["skill", "install", "--target", "claude-code", "--apply"])

    assert result.exit_code == 0, result.output
    assert "stale content" not in dest.read_text(encoding="utf-8")


def test_install_json_output_dry_run(home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["skill", "install", "--target", "claude-code", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["mode"] == "dry-run"
    assert payload["target"] == "claude-code"
    assert payload["destination"].endswith("skills/netbox-super-cli/SKILL.md")
    assert payload["manual"] is False


def test_install_json_output_apply(home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app, ["skill", "install", "--target", "claude-code", "--apply", "--output", "json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["mode"] == "apply"
    assert payload["written"] is True
    assert Path(payload["destination"]).exists()


def test_install_json_output_manual_target(home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["skill", "install", "--target", "copilot", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["manual"] is True
    assert payload["destination"] is None
    assert "instructions" in payload


@pytest.mark.parametrize("target", ["claude-code", "codex", "gemini", "copilot"])
def test_install_dry_run_all_targets_exit_0(home: Path, target: str) -> None:
    """Every documented target must dry-run successfully (exit 0)."""
    runner = CliRunner()
    result = runner.invoke(app, ["skill", "install", "--target", target])

    assert result.exit_code == 0, result.output


def test_install_unknown_target_exits_nonzero(home: Path) -> None:
    """Typer enforces the --target enum at parse time."""
    runner = CliRunner()
    result = runner.invoke(app, ["skill", "install", "--target", "bogus"])

    assert result.exit_code != 0
