"""Phase 3d — bulk-capable POST stays one HTTP call; --no-bulk loops sequentially."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.usefixtures("clean_tags")


def _five_tag_yaml(tmp_path: Path, prefix: str) -> Path:
    lines = []
    for i in range(5):
        lines.append(f"- name: {prefix}-{i}\n  slug: {prefix}-{i}\n")
    target = tmp_path / f"{prefix}.yaml"
    target.write_text("".join(lines), encoding="utf-8")
    return target


def _audit_lines(home: Path) -> list[dict]:
    audit = home / "logs" / "audit.jsonl"
    if not audit.exists():
        return []
    out = []
    for raw in audit.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line:
            out.append(json.loads(line))
    return out


def test_bulk_create_uses_single_request(
    run_nsc,
    netbox_client: httpx.Client,
    tmp_nsc_home: Path,
    tmp_path: Path,
) -> None:
    payload = _five_tag_yaml(tmp_path, "bulk")

    r = run_nsc("extras", "tags", "create", "-f", str(payload), "--apply", "--output", "json")
    assert r.returncode == 0, r.stderr

    # NetBox state: all 5 tags present
    listing = netbox_client.get("/api/extras/tags/").json()
    assert listing["count"] == 5
    names = sorted(t["name"] for t in listing["results"])
    assert names == [f"bulk-{i}" for i in range(5)]

    # Audit log: bulk path → one entry covering all 5 records
    entries = _audit_lines(tmp_nsc_home)
    bulk_entries = [e for e in entries if e["method"] == "POST"]
    assert len(bulk_entries) == 1, [e["record_indices"] for e in bulk_entries]
    assert bulk_entries[0]["record_indices"] == [0, 1, 2, 3, 4]


def test_no_bulk_loop_fallback_uses_n_requests(
    run_nsc,
    netbox_client: httpx.Client,
    tmp_nsc_home: Path,
    tmp_path: Path,
) -> None:
    payload = _five_tag_yaml(tmp_path, "loop")

    r = run_nsc(
        "extras",
        "tags",
        "create",
        "-f",
        str(payload),
        "--no-bulk",
        "--apply",
        "--output",
        "json",
    )
    assert r.returncode == 0, r.stderr

    listing = netbox_client.get("/api/extras/tags/").json()
    assert listing["count"] == 5

    entries = _audit_lines(tmp_nsc_home)
    loop_entries = [e for e in entries if e["method"] == "POST"]
    assert len(loop_entries) == 5, [e["record_indices"] for e in loop_entries]
    indices = sorted(e["record_indices"][0] for e in loop_entries)
    assert indices == [0, 1, 2, 3, 4]
