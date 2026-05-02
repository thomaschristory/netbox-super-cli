"""Phase 3d — server-side validation surfaces as a `validation` envelope (source=server)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.usefixtures("clean_tags")


def _tag_yaml(tmp_path: Path, name: str) -> Path:
    p = tmp_path / f"{name}.yaml"
    p.write_text(f"name: {name}\nslug: {name}\n", encoding="utf-8")
    return p


def test_netbox_400_surfaces_as_validation_envelope(
    run_nsc,
    netbox_client: httpx.Client,
    tmp_path: Path,
) -> None:
    payload = _tag_yaml(tmp_path, "dup-3d")

    # Seed: first create succeeds.
    r = run_nsc("extras", "tags", "create", "-f", str(payload), "--apply", "--output", "json")
    assert r.returncode == 0, r.stderr

    # Same payload again — NetBox enforces unique slug, returns 400.
    r = run_nsc("extras", "tags", "create", "-f", str(payload), "--apply", "--output", "json")
    assert r.returncode == 4, (r.returncode, r.stdout, r.stderr)

    envelope = json.loads(r.stdout)
    assert envelope["type"] == "validation"
    assert envelope["details"]["source"] == "server"
    assert envelope["status_code"] == 400

    # Only one tag should exist (the seed).
    assert netbox_client.get("/api/extras/tags/").json()["count"] == 1
