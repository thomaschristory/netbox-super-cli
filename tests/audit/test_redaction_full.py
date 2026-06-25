"""Phase 6: `audit_redaction: full` — strip every body from audit lines.

In `full` mode an audit line carries ONLY routing metadata
(`{method, url, status_code, timestamp, profile}`) regardless of body shape
or size. These tests assert no body/header/query content can leak.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nsc.config.models import AuditRedaction
from nsc.http.audit import AuditEntry, append_audit_jsonl
from nsc.model.command_model import HttpMethod

_ALLOWED_KEYS = {"method", "url", "status_code", "timestamp", "profile"}


def _entry(*, request_body: Any, response_body: Any) -> AuditEntry:
    return AuditEntry(
        timestamp="2026-06-25T12:00:00.000Z",
        operation_id="users_users_create",
        method=HttpMethod.POST,
        url="https://nb/api/users/users/",
        request_headers={"Authorization": "Token abc123"},
        request_query={"q": "secret-search"},
        request_body=request_body,
        sensitive_paths=(),
        response_status_code=201,
        response_headers={"Set-Cookie": "sessionid=topsecret"},
        response_body=response_body,
        duration_ms=42,
        profile="prod",
        redaction=AuditRedaction.FULL,
    )


def _emit(entry: AuditEntry, tmp_path: Path) -> dict[str, Any]:
    p = tmp_path / "audit.jsonl"
    append_audit_jsonl(entry, path=p)
    parsed: dict[str, Any] = json.loads(p.read_text().splitlines()[0])
    return parsed


def _assert_only_allowed(line: dict[str, Any]) -> None:
    assert set(line.keys()) == _ALLOWED_KEYS
    blob = json.dumps(line)
    for leak in ("abc123", "secret-search", "topsecret", "password", "hunter2"):
        assert leak not in blob


def test_full_small_json_body(tmp_path: Path) -> None:
    entry = _entry(
        request_body={"username": "alice", "password": "hunter2"},
        response_body={"id": 1, "username": "alice"},
    )
    line = _emit(entry, tmp_path)
    _assert_only_allowed(line)
    assert line == {
        "method": "POST",
        "url": "https://nb/api/users/users/",
        "status_code": 201,
        "timestamp": "2026-06-25T12:00:00.000Z",
        "profile": "prod",
    }


def test_full_large_json_body(tmp_path: Path) -> None:
    big = {"items": [{"i": i, "password": "hunter2"} for i in range(5000)]}
    entry = _entry(request_body=big, response_body=big)
    line = _emit(entry, tmp_path)
    _assert_only_allowed(line)


def test_full_error_envelope_body(tmp_path: Path) -> None:
    envelope = {
        "error": {
            "kind": "validation",
            "message": "token 'abc123' is invalid",
            "details": {"password": ["hunter2 is too weak"]},
        }
    }
    entry = _entry(request_body={"password": "hunter2"}, response_body=envelope)
    line = _emit(entry, tmp_path)
    _assert_only_allowed(line)


def test_full_multipart_body(tmp_path: Path) -> None:
    multipart = (
        "--boundary\r\n"
        'Content-Disposition: form-data; name="password"\r\n\r\n'
        "hunter2\r\n"
        "--boundary--\r\n"
    )
    entry = _entry(request_body=multipart, response_body="ok")
    line = _emit(entry, tmp_path)
    _assert_only_allowed(line)


def test_full_omits_response_when_status_none(tmp_path: Path) -> None:
    entry = AuditEntry(
        timestamp="2026-06-25T12:00:00.000Z",
        method=HttpMethod.DELETE,
        url="https://nb/api/dcim/devices/1/",
        request_body=None,
        response_status_code=None,
        profile="prod",
        redaction=AuditRedaction.FULL,
    )
    line = _emit(entry, tmp_path)
    assert set(line.keys()) == _ALLOWED_KEYS
    assert line["status_code"] is None


def test_safe_remains_default_and_keeps_body(tmp_path: Path) -> None:
    entry = AuditEntry(
        timestamp="2026-06-25T12:00:00.000Z",
        method=HttpMethod.POST,
        url="https://nb/api/users/users/",
        request_body={"username": "alice", "password": "hunter2"},
        sensitive_paths=("password",),
        response_status_code=201,
        response_body={"id": 1},
        profile="prod",
    )
    assert entry.redaction is AuditRedaction.SAFE
    line = _emit(entry, tmp_path)
    assert line["request"]["body"] == {"username": "alice", "password": "<redacted>"}
    assert "schema_version" in line


@pytest.mark.parametrize("missing", sorted(_ALLOWED_KEYS))
def test_full_always_contains_each_allowed_key(tmp_path: Path, missing: str) -> None:
    entry = _entry(request_body={"x": 1}, response_body={"y": 2})
    line = _emit(entry, tmp_path)
    assert missing in line


def test_full_url_strips_query_and_credentials(tmp_path: Path) -> None:
    """A debug-mode GET can carry filter params + basic-auth userinfo in the URL.

    `full` mode must reduce the URL to scheme + host + path so neither the query
    string (which may hold a `private_key` filter) nor the `user:pass@` userinfo
    leaks into the audit line.
    """
    entry = AuditEntry(
        timestamp="2026-06-25T12:00:00.000Z",
        method=HttpMethod.GET,
        url="https://user:pass@nb/api/x/?private_key=SECRETVAL&q=a",
        request_body=None,
        response_status_code=200,
        profile="prod",
        redaction=AuditRedaction.FULL,
    )
    line = _emit(entry, tmp_path)
    assert set(line.keys()) == _ALLOWED_KEYS
    assert line["url"] == "https://nb/api/x/"
    blob = json.dumps(line)
    for leak in ("SECRETVAL", "private_key", "pass", "user"):
        assert leak not in blob


def test_full_url_with_port_preserved(tmp_path: Path) -> None:
    entry = AuditEntry(
        timestamp="2026-06-25T12:00:00.000Z",
        method=HttpMethod.GET,
        url="https://nb:8443/api/x/?q=a",
        request_body=None,
        response_status_code=200,
        profile="prod",
        redaction=AuditRedaction.FULL,
    )
    line = _emit(entry, tmp_path)
    assert line["url"] == "https://nb:8443/api/x/"


def test_full_url_no_query_or_userinfo_is_noop(tmp_path: Path) -> None:
    entry = AuditEntry(
        timestamp="2026-06-25T12:00:00.000Z",
        method=HttpMethod.GET,
        url="https://nb/api/x/",
        request_body=None,
        response_status_code=200,
        profile="prod",
        redaction=AuditRedaction.FULL,
    )
    line = _emit(entry, tmp_path)
    assert line["url"] == "https://nb/api/x/"


def test_full_excludes_hypothetical_extra_entry_field(tmp_path: Path) -> None:
    """Regression guard: `full` lines are an allow-list, not a deny-list.

    If a new field is added to `AuditEntry`, it must not silently appear in a
    `full` line. The emitted key set stays pinned to `_ALLOWED_KEYS`.
    """
    entry = _entry(request_body={"x": 1}, response_body={"y": 2})
    line = _emit(entry, tmp_path)
    extra = set(line.keys()) - _ALLOWED_KEYS
    assert extra == set(), f"unexpected keys leaked into full line: {extra}"
