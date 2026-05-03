"""Phase 4d: emit-time body redaction in audit.jsonl."""

from __future__ import annotations

import json
from pathlib import Path

from nsc.http.audit import (
    AuditEntry,
    append_audit_jsonl,
    redact_body,
)
from nsc.model.command_model import HttpMethod


def test_redact_body_passthrough_on_empty_paths() -> None:
    body = {"name": "alpha", "password": "secret"}
    assert redact_body(body, ()) == {"name": "alpha", "password": "secret"}


def test_redact_top_level_field() -> None:
    body = {"name": "alpha", "password": "hunter2"}
    out = redact_body(body, ("password",))
    assert out == {"name": "alpha", "password": "<redacted>"}
    assert body["password"] == "hunter2"


def test_redact_nested_field() -> None:
    body = {"auth": {"username": "u", "password": "hunter2"}, "name": "x"}
    out = redact_body(body, ("auth.password",))
    assert out == {"auth": {"username": "u", "password": "<redacted>"}, "name": "x"}
    assert body["auth"]["password"] == "hunter2"


def test_redact_array_of_objects() -> None:
    body = {
        "members": [
            {"username": "a", "secret": "s1"},
            {"username": "b", "secret": "s2"},
        ],
    }
    out = redact_body(body, ("members.secret",))
    assert out == {
        "members": [
            {"username": "a", "secret": "<redacted>"},
            {"username": "b", "secret": "<redacted>"},
        ],
    }


def test_redact_missing_path_is_noop() -> None:
    body = {"name": "alpha"}
    assert redact_body(body, ("password", "nested.key")) == {"name": "alpha"}


def test_redact_handles_none_body() -> None:
    assert redact_body(None, ("password",)) is None


def test_redact_multiple_paths() -> None:
    body = {"password": "p", "auth": {"token": "t"}, "name": "n"}
    out = redact_body(body, ("password", "auth.token"))
    assert out == {"password": "<redacted>", "auth": {"token": "<redacted>"}, "name": "n"}


def test_redact_preserves_value_when_path_segment_is_a_scalar() -> None:
    body = {"auth": "not an object"}
    out = redact_body(body, ("auth.password",))
    assert out == {"auth": "not an object"}


def test_audit_entry_redacts_request_body_in_jsonl(tmp_path: Path) -> None:
    p = tmp_path / "audit.jsonl"
    entry = AuditEntry(
        timestamp="2026-05-03T12:00:00.000Z",
        operation_id="users_users_create",
        method=HttpMethod.POST,
        url="https://nb/api/users/users/",
        request_headers={},
        request_query={},
        request_body={"username": "alice", "password": "hunter2"},
        sensitive_paths=("password",),
        response_status_code=201,
        response_headers={},
        response_body={"id": 1, "username": "alice"},
        duration_ms=42,
        attempt_n=1,
        final_attempt=True,
        error_kind=None,
        dry_run=False,
        preflight_blocked=False,
        record_indices=[0],
        applied=True,
        explain=False,
    )
    append_audit_jsonl(entry, path=p)
    line = json.loads(p.read_text().splitlines()[0])
    assert line["request"]["body"] == {"username": "alice", "password": "<redacted>"}


def test_audit_entry_default_sensitive_paths_is_empty() -> None:
    entry = AuditEntry(
        timestamp="2026-05-03T12:00:00.000Z",
        method=HttpMethod.GET,
        url="https://nb/api/dcim/devices/",
        request_headers={},
        request_query={},
        request_body=None,
    )
    assert entry.sensitive_paths == ()
