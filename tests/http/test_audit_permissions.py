"""Audit log file/directory permissions (security audit M4).

Audit logs contain request/response bodies verbatim and must not be
world-readable on shared hosts, mirroring the 0600 treatment of config.yaml.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from nsc.http import audit
from nsc.http.audit import AuditEntry, append_audit_jsonl, write_last_request
from nsc.model.command_model import HttpMethod


def _entry() -> AuditEntry:
    return AuditEntry(timestamp="2026-01-01T00:00:00Z", method=HttpMethod.POST, url="https://x/a/")


def test_append_creates_file_0600_and_dir_0700(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    path = log_dir / "audit.jsonl"
    append_audit_jsonl(_entry(), path=path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(log_dir.stat().st_mode) == 0o700


def test_append_downgrades_preexisting_world_readable_file(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "audit.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("", encoding="utf-8")
    path.chmod(0o644)
    append_audit_jsonl(_entry(), path=path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_rotated_file_is_not_world_readable(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "audit.jsonl"
    append_audit_jsonl(_entry(), path=path, rotate_bytes=1)
    append_audit_jsonl(_entry(), path=path, rotate_bytes=1)
    rolled = path.with_suffix(path.suffix + ".1")
    assert rolled.exists()
    assert stat.S_IMODE(rolled.stat().st_mode) == 0o600


def test_last_request_dir_0700(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    path = log_dir / "last-request.json"
    write_last_request(_entry(), path=path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(log_dir.stat().st_mode) == 0o700


def test_append_tightens_preexisting_world_readable_dir(tmp_path: Path) -> None:
    """A logs dir left 0755 by an older version / permissive umask is clamped to 0700."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_dir.chmod(0o755)
    append_audit_jsonl(_entry(), path=log_dir / "audit.jsonl")
    assert stat.S_IMODE(log_dir.stat().st_mode) == 0o700


def test_append_clamps_created_state_root_to_0700(tmp_path: Path) -> None:
    """The `~/.nsc` root created as a side effect of writing `logs/` is owner-only."""
    root = tmp_path / ".nsc"
    append_audit_jsonl(_entry(), path=root / "logs" / "audit.jsonl")
    assert stat.S_IMODE(root.stat().st_mode) == 0o700


def test_file_created_0600_by_open_mode_not_just_chmod(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the post-create chmod neutralized and a permissive umask, the os.open
    mode alone must still yield 0600 — proving no world-readable TOCTOU window."""
    monkeypatch.setattr(audit.os, "chmod", lambda *a, **k: None)
    old_umask = os.umask(0o000)
    try:
        path = tmp_path / "logs" / "audit.jsonl"
        append_audit_jsonl(_entry(), path=path)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    finally:
        os.umask(old_umask)
