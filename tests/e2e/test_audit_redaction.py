"""Phase 4d e2e: password field round-trip — wire body unredacted, audit log redacted."""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest


def _audit_lines(home: Path) -> list[dict[str, object]]:
    audit = home / "logs" / "audit.jsonl"
    if not audit.exists():
        return []
    return [json.loads(ln) for ln in audit.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_user_password_is_redacted_in_audit(
    run_nsc: Callable[..., object],
    netbox_client: httpx.Client,
    tmp_nsc_home: Path,
    tmp_path: Path,
) -> None:
    """Create a user with a password; the wire body succeeds, the audit shows <redacted>."""
    plaintext_password = "p4d-redact-" + secrets.token_hex(8)
    username = "p4d-redact-" + secrets.token_hex(4)

    record = tmp_path / "user.json"
    record.write_text(
        json.dumps({"username": username, "password": plaintext_password}),
        encoding="utf-8",
    )

    created_id: int | None = None
    try:
        r = run_nsc(  # type: ignore[call-arg]
            "users",
            "users",
            "create",
            "-f",
            str(record),
            "--apply",
            "--output",
            "json",
        )
        assert hasattr(r, "returncode"), "run_nsc must return a CompletedNsc"
        if r.returncode == 8:  # type: ignore[attr-defined]
            pytest.skip("v1 token cannot create users on this NetBox build (auth_error)")
        # Permissions / validation issue — surface stdout/stderr for debugging.
        assert r.returncode == 0, (r.stdout, r.stderr)  # type: ignore[attr-defined]
        created = json.loads(r.stdout)  # type: ignore[attr-defined]
        assert created["username"] == username
        created_id = created["id"]

        # Verify NetBox actually has the user (proves the wire body had the password).
        check = netbox_client.get(f"/api/users/users/{created_id}/")
        assert check.status_code == 200, check.text

        # Verify the audit line for the create shows <redacted>.
        lines = _audit_lines(tmp_nsc_home)
        creates = [
            ln
            for ln in lines
            if ln.get("operation_id") == "users_users_create" and ln.get("method") == "POST"
        ]
        assert creates, (
            f"no users_users_create audit line; saw: {[ln.get('operation_id') for ln in lines]}"
        )
        body = creates[0]["request"]["body"]
        assert isinstance(body, dict), body
        assert body["username"] == username
        assert body["password"] == "<redacted>", body

        # Defence-in-depth: the plaintext must appear NOWHERE in the audit file.
        audit_text = (tmp_nsc_home / "logs" / "audit.jsonl").read_text(encoding="utf-8")
        assert plaintext_password not in audit_text, "plaintext password leaked into audit.jsonl"

    finally:
        if created_id is not None:
            netbox_client.delete(f"/api/users/users/{created_id}/")
