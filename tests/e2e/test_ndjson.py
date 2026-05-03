"""Phase 4d e2e: bulk-create from a real NDJSON file against live NetBox."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.usefixtures("clean_tags")


def _write_ndjson(tmp_path: Path, records: list[dict[str, object]]) -> Path:
    """Write records as NDJSON (one JSON object per line)."""
    target = tmp_path / "records.ndjson"
    target.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )
    return target


def test_bulk_create_tags_from_ndjson_file(
    run_nsc,
    netbox_client: httpx.Client,
    tmp_path: Path,
) -> None:
    """Three tags created via NDJSON; verify all three exist on the server."""
    records = [
        {"name": "p4d-ndjson-1", "slug": "p4d-ndjson-1"},
        {"name": "p4d-ndjson-2", "slug": "p4d-ndjson-2"},
        {"name": "p4d-ndjson-3", "slug": "p4d-ndjson-3"},
    ]
    ndjson_file = _write_ndjson(tmp_path, records)

    r = run_nsc(
        "extras",
        "tags",
        "create",
        "-f",
        str(ndjson_file),
        "--apply",
        "--output",
        "json",
    )
    assert r.returncode == 0, (r.stdout, r.stderr)

    # Cross-check via direct NetBox query.
    listing = netbox_client.get("/api/extras/tags/", params={"limit": 200}).json()
    names = {tag["name"] for tag in listing.get("results", [])}
    assert names >= {rec["name"] for rec in records}


def test_ndjson_parse_failure_aborts_before_wire(
    run_nsc,
    netbox_client: httpx.Client,
    tmp_path: Path,
) -> None:
    """One bad line aborts the whole batch; no records are created on the server."""
    ndjson_file = tmp_path / "bad.ndjson"
    ndjson_file.write_text(
        '{"name": "p4d-bad-1", "slug": "p4d-bad-1"}\n'
        "not json at all\n"
        '{"name": "p4d-bad-3", "slug": "p4d-bad-3"}\n',
        encoding="utf-8",
    )

    pre_count = netbox_client.get("/api/extras/tags/").json().get("count", 0)

    r = run_nsc(
        "extras",
        "tags",
        "create",
        "-f",
        str(ndjson_file),
        "--apply",
        "--output",
        "json",
    )
    assert r.returncode == 4, (r.stdout, r.stderr)
    payload = json.loads(r.stdout)
    assert payload["type"] == "input_error"
    assert payload["details"]["bad_lines"][0]["line"] == 2

    # No new tags should have been created.
    post_count = netbox_client.get("/api/extras/tags/").json().get("count", 0)
    assert post_count == pre_count
