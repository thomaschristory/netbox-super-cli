"""Phase 4d: client public methods accept sensitive_paths and write them into the audit entry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from nsc.http.client import NetBoxClient


class _FakeProfile:
    def __init__(self, **overrides: Any) -> None:
        self.url: str = overrides.get("url", "https://nb.example")
        self.token: str | None = overrides.get("token", "tok")
        self.verify_ssl: bool = overrides.get("verify_ssl", True)
        self.timeout: float = overrides.get("timeout", 5.0)


def test_client_post_threads_sensitive_paths_into_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Logs go to a tmp dir so the test is hermetic.
    monkeypatch.setenv("NSC_HOME", str(tmp_path))
    client = NetBoxClient(_FakeProfile(url="https://nb.example"))
    with respx.mock(base_url="https://nb.example") as m:
        m.post("/api/users/users/").mock(return_value=httpx.Response(201, json={"id": 1}))
        client.post(
            "/api/users/users/",
            json={"username": "alice", "password": "hunter2"},
            operation_id="users_users_create",
            record_indices=[0],
            sensitive_paths=("password",),
        )
    audit_path = tmp_path / "logs" / "audit.jsonl"
    assert audit_path.exists(), f"audit.jsonl not found under {tmp_path}"
    line = json.loads(audit_path.read_text().splitlines()[0])
    assert line["request"]["body"] == {"username": "alice", "password": "<redacted>"}
