"""Audit log writers — last-request.json + audit.jsonl (Phase 3a)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from nsc.http.audit import (
    AuditEntry,
    append_audit_jsonl,
    redact_headers,
    truncate_body,
    write_last_request,
)
from nsc.model.command_model import HttpMethod


def _entry(**overrides: object) -> AuditEntry:
    base: dict[str, object] = {
        "timestamp": "2026-05-01T17:42:13.215Z",
        "operation_id": "dcim_devices_list",
        "method": HttpMethod.GET,
        "url": "https://nb/api/dcim/devices/",
        "request_headers": {"Authorization": "Token secret", "Accept": "application/json"},
        "request_query": {},
        "request_body": None,
        "response_status_code": 200,
        "response_headers": {"Content-Type": "application/json"},
        "response_body": {"results": []},
        "duration_ms": 42,
        "attempt_n": 1,
        "final_attempt": True,
        "error_kind": None,
        "dry_run": False,
        "preflight_blocked": False,
        "record_indices": [],
        "applied": False,
        "explain": False,
    }
    base.update(overrides)
    return AuditEntry(**base)  # type: ignore[arg-type]


def test_redact_headers_redacts_sensitive_case_insensitive() -> None:
    out = redact_headers(
        {
            "Authorization": "Token secret",
            "authorization": "Token secret",
            "Cookie": "sid=abc",
            "X-API-Key": "k",
            "Content-Type": "application/json",
        }
    )
    assert out["Authorization"] == "<redacted>"
    assert out["authorization"] == "<redacted>"
    assert out["Cookie"] == "<redacted>"
    assert out["X-API-Key"] == "<redacted>"
    assert out["Content-Type"] == "application/json"


def test_truncate_body_below_cap_returns_unchanged() -> None:
    body = {"a": 1, "b": "x"}
    out, truncated = truncate_body(body, cap_bytes=1024)
    assert out == body
    assert truncated is False


def test_truncate_body_above_cap_returns_marker() -> None:
    huge = {"x": "a" * 1024}
    out, truncated = truncate_body(huge, cap_bytes=128)
    assert truncated is True
    assert out["_truncated"] is True
    assert isinstance(out["_size_bytes"], int)
    assert out["_size_bytes"] > 128


def test_truncate_body_none_passthrough() -> None:
    out, truncated = truncate_body(None, cap_bytes=1024)
    assert out is None
    assert truncated is False


def test_write_last_request_atomic_to_path(tmp_path: Path) -> None:
    target = tmp_path / "logs" / "last-request.json"
    e = _entry()
    write_last_request(e, path=target)
    parsed = json.loads(target.read_text())
    assert parsed["method"] == "GET"
    assert parsed["request"]["headers"]["Authorization"] == "<redacted>"
    assert parsed["schema_version"] == 1


def test_write_last_request_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "logs" / "last-request.json"
    write_last_request(_entry(operation_id="a"), path=target)
    write_last_request(_entry(operation_id="b"), path=target)
    parsed = json.loads(target.read_text())
    assert parsed["operation_id"] == "b"


def test_append_audit_jsonl_writes_one_line_per_call(tmp_path: Path) -> None:
    target = tmp_path / "logs" / "audit.jsonl"
    append_audit_jsonl(_entry(operation_id="a"), path=target)
    append_audit_jsonl(_entry(operation_id="b"), path=target)
    lines = target.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["operation_id"] == "a"
    assert json.loads(lines[1])["operation_id"] == "b"


def test_append_audit_jsonl_rotates_at_size_threshold(tmp_path: Path) -> None:
    target = tmp_path / "logs" / "audit.jsonl"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
    append_audit_jsonl(_entry(operation_id="a"), path=target, rotate_bytes=10 * 1024 * 1024)
    rolled = target.with_suffix(target.suffix + ".1")
    assert rolled.exists()
    assert target.read_text().count("\n") == 1
    assert json.loads(target.read_text())["operation_id"] == "a"


def test_append_audit_jsonl_rotation_overwrites_prior_dot_one(tmp_path: Path) -> None:
    target = tmp_path / "logs" / "audit.jsonl"
    target.parent.mkdir(parents=True)
    rolled = target.with_suffix(target.suffix + ".1")
    rolled.write_text("OLD")
    target.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
    append_audit_jsonl(_entry(operation_id="new"), path=target, rotate_bytes=10 * 1024 * 1024)
    assert "OLD" not in rolled.read_text()


def test_write_failure_emits_stderr_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    if os.geteuid() == 0:
        pytest.skip("requires non-root")
    target = tmp_path / "ro" / "last-request.json"
    target.parent.mkdir()
    target.parent.chmod(0o400)
    try:
        write_last_request(_entry(), path=target)  # must not raise
    finally:
        target.parent.chmod(0o700)
    err = capsys.readouterr().err
    assert "audit log" in err.lower() or "could not write" in err.lower()
