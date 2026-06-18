"""Tests for scripts/sync_agents_md.py (the CLAUDE.md -> AGENTS.md mirror)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _import_module() -> ModuleType:
    """Import scripts/sync_agents_md.py without it being a package member."""
    path = REPO_ROOT / "scripts" / "sync_agents_md.py"
    spec = importlib.util.spec_from_file_location("sync_agents_md", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_render_prepends_header_to_claude_md() -> None:
    m = _import_module()
    out = m.render()
    assert out.startswith(m._HEADER)
    assert "netbox-super-cli" in out


def test_check_passes_when_in_sync() -> None:
    """The committed AGENTS.md must already match CLAUDE.md."""
    m = _import_module()
    assert m.main(["--check"]) == 0


def test_check_prints_unified_diff_on_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """On drift, --check prints a unified diff (issue #11) before the summary line."""
    m = _import_module()
    drifted = tmp_path / "AGENTS.md"
    drifted.write_text("totally different\n", encoding="utf-8")
    monkeypatch.setattr(m, "DEST", drifted)
    rc = m.main(["--check"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "@@" in err  # unified-diff hunk header
    assert "out of date" in err


def test_check_no_diff_suppresses_unified_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    m = _import_module()
    drifted = tmp_path / "AGENTS.md"
    drifted.write_text("totally different\n", encoding="utf-8")
    monkeypatch.setattr(m, "DEST", drifted)
    rc = m.main(["--check", "--no-diff"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "@@" not in err
    assert "out of date" in err
