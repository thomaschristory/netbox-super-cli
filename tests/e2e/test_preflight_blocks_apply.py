"""Phase 3d — preflight blocks --apply before any HTTP call."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.usefixtures("clean_tags")


def test_missing_required_field_blocks_apply(
    run_nsc,
    netbox_client: httpx.Client,
    tmp_path: Path,
) -> None:
    # Tag without `slug` — spec §4.6 says required-field check fires before the wire.
    yaml = tmp_path / "broken.yaml"
    yaml.write_text("name: phase-3d-broken\n", encoding="utf-8")

    r = run_nsc("extras", "tags", "create", "-f", str(yaml), "--apply", "--output", "json")
    assert r.returncode == 4, (r.returncode, r.stdout, r.stderr)

    envelope = json.loads(r.stdout)
    assert envelope["type"] == "validation"
    assert envelope["details"]["source"] == "preflight"
    issues = envelope["details"]["issues"]
    assert any(
        issue["kind"] == "missing_required" and issue["field_path"] == "slug" for issue in issues
    ), issues

    # Wire was never touched — NetBox is still empty.
    assert netbox_client.get("/api/extras/tags/").json()["count"] == 0
