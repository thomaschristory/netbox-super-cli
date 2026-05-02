"""Phase 3d primary lifecycle test: list → create → delete cycle on extras/tags.

Each step asserts both:
- the CLI's exit code and stdout/stderr (the agent contract),
- the actual NetBox state (via the netbox_client fixture).

If only the first kind of assertion passes, we'd be re-testing what respx already
covers. The whole point of e2e is the second kind.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.usefixtures("clean_tags")


def _create_payload() -> dict[str, object]:
    return {"name": "phase-3d-tag", "slug": "phase-3d-tag"}


def _write_tag_yaml(tmp_path: Path) -> Path:
    body = "name: phase-3d-tag\nslug: phase-3d-tag\n"
    target = tmp_path / "tag.yaml"
    target.write_text(body, encoding="utf-8")
    return target


def _audit_line_count(home: Path) -> int:
    audit = home / "logs" / "audit.jsonl"
    if not audit.exists():
        return 0
    return sum(1 for line in audit.read_text(encoding="utf-8").splitlines() if line.strip())


def test_full_lifecycle_list_create_delete(
    run_nsc,
    netbox_client: httpx.Client,
    tmp_nsc_home: Path,
    tmp_path: Path,
) -> None:
    # Step 1: list — empty.
    # nsc renders --output json as the records array directly (no NetBox-style
    # {"count","results"} wrapper); plan §Task 3 was wrong about the shape and
    # has been corrected here against live behaviour.
    r = run_nsc("extras", "tags", "list", "--output", "json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == []

    # Step 2: create dry-run — must NOT touch NetBox
    yaml_file = _write_tag_yaml(tmp_path)
    pre_audit = _audit_line_count(tmp_nsc_home)
    r = run_nsc("extras", "tags", "create", "-f", str(yaml_file), "--explain", "--output", "json")
    assert r.returncode == 0, r.stderr
    trace = json.loads(r.stdout)
    assert trace["operation_id"].startswith("extras_tags_create"), trace
    assert trace["requests"][0]["method"] == "POST"
    # NetBox is unchanged
    assert netbox_client.get("/api/extras/tags/").json()["count"] == 0
    # Dry-run still appends an audit line (§4.3)
    assert _audit_line_count(tmp_nsc_home) == pre_audit + 1

    # Step 3: create --apply — actually creates
    r = run_nsc("extras", "tags", "create", "-f", str(yaml_file), "--apply", "--output", "json")
    assert r.returncode == 0, r.stderr
    created = json.loads(r.stdout)
    tag_id = created["id"]
    assert created["name"] == "phase-3d-tag"
    # Audit appended again
    assert _audit_line_count(tmp_nsc_home) == pre_audit + 2
    # last-request.json written (apply path only — §4.3)
    assert (tmp_nsc_home / "logs" / "last-request.json").exists()

    # Step 4: list round-trip
    r = run_nsc("extras", "tags", "list", "--output", "json")
    assert r.returncode == 0, r.stderr
    listing = json.loads(r.stdout)
    assert len(listing) == 1
    assert listing[0]["id"] == tag_id

    # Step 5: delete dry-run — must not actually delete
    r = run_nsc("extras", "tags", "delete", str(tag_id), "--output", "json")
    assert r.returncode == 0, r.stderr
    assert netbox_client.get(f"/api/extras/tags/{tag_id}/").status_code == 200

    # Step 6: delete --apply
    r = run_nsc("extras", "tags", "delete", str(tag_id), "--apply", "--output", "json")
    assert r.returncode == 0, r.stderr
    assert netbox_client.get(f"/api/extras/tags/{tag_id}/").status_code == 404

    # Step 7: delete --apply again — default = exit 0 with already_absent
    r = run_nsc("extras", "tags", "delete", str(tag_id), "--apply", "--output", "json")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload == {"deleted": False, "reason": "already_absent"}

    # Step 8: delete --apply --strict on the same id — exit 9 (not_found)
    r = run_nsc("extras", "tags", "delete", str(tag_id), "--apply", "--strict", "--output", "json")
    assert r.returncode == 9, (r.returncode, r.stdout, r.stderr)
    envelope = json.loads(r.stdout)
    assert envelope["type"] == "not_found"
