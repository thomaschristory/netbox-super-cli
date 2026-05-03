"""Tests for the schema → CommandModel builder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nsc.builder.build import build_command_model
from nsc.model.command_model import HttpMethod, ParameterLocation
from nsc.schema.hashing import canonical_sha256
from nsc.schema.loader import LoadedSchema, load_schema
from nsc.schema.models import OpenAPIDocument


def _make_loaded_schema(
    path: str,
    method: str,
    operation_id: str,
    tags: list[str],
) -> LoadedSchema:
    """Build a minimal LoadedSchema with a single operation for testing."""
    doc_dict: dict = {
        "openapi": "3.0.3",
        "info": {"title": "Test", "version": "0.0.1"},
        "paths": {
            path: {
                method: {
                    "operationId": operation_id,
                    "tags": tags,
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
    body = json.dumps(doc_dict).encode()
    h = canonical_sha256(body)
    doc = OpenAPIDocument.model_validate(doc_dict)
    return LoadedSchema(source="<test>", body=body, hash=h, document=doc)


@pytest.fixture(scope="module")
def bundled_schema_path() -> Path:
    bundled = Path(__file__).resolve().parents[2] / "nsc" / "schemas" / "bundled"
    candidates = sorted(bundled.glob("netbox-*.json.gz"))
    assert candidates, "no bundled schema available"
    return candidates[-1]


def test_builds_against_bundled_schema(bundled_schema_path: Path) -> None:
    loaded = load_schema(str(bundled_schema_path))
    model = build_command_model(loaded)
    assert model.info_title.lower().startswith("netbox")
    assert model.schema_hash == loaded.hash
    # NetBox always exposes dcim.devices with full CRUD
    assert "dcim" in model.tags
    devices = model.tags["dcim"].resources["devices"]
    assert devices.list_op is not None
    assert devices.get_op is not None
    assert devices.create_op is not None
    assert devices.update_op is not None  # PATCH
    assert devices.replace_op is not None  # PUT
    assert devices.delete_op is not None


def test_list_operation_is_get_and_collection_path(bundled_schema_path: Path) -> None:
    loaded = load_schema(str(bundled_schema_path))
    model = build_command_model(loaded)
    op = model.tags["dcim"].resources["devices"].list_op
    assert op is not None
    assert op.http_method == HttpMethod.GET
    assert op.path.endswith("/devices/")
    assert "{" not in op.path  # no path params on the list endpoint


def test_get_operation_path_has_id(bundled_schema_path: Path) -> None:
    loaded = load_schema(str(bundled_schema_path))
    model = build_command_model(loaded)
    op = model.tags["dcim"].resources["devices"].get_op
    assert op is not None
    assert op.http_method == HttpMethod.GET
    assert "{id}" in op.path


def test_query_filter_parameters_are_extracted(bundled_schema_path: Path) -> None:
    loaded = load_schema(str(bundled_schema_path))
    model = build_command_model(loaded)
    op = model.tags["dcim"].resources["devices"].list_op
    assert op is not None
    names = {p.name for p in op.parameters if p.location == ParameterLocation.QUERY}
    # NetBox always exposes a name filter on devices.
    assert "name" in names


def test_custom_actions_appear_under_parent_resource(bundled_schema_path: Path) -> None:
    loaded = load_schema(str(bundled_schema_path))
    model = build_command_model(loaded)
    prefixes = model.tags["ipam"].resources.get("prefixes")
    assert prefixes is not None
    custom = {op.operation_id: op for op in prefixes.custom_actions}
    # /api/ipam/prefixes/{id}/available-ips/ exists in NetBox >=4.x
    assert any("available_ips" in oid for oid in custom), (
        f"available-ips action not found; got {sorted(custom)}"
    )


def test_iter_operations_yields_at_least_a_few_hundred(bundled_schema_path: Path) -> None:
    loaded = load_schema(str(bundled_schema_path))
    model = build_command_model(loaded)
    count = sum(1 for _ in model.iter_operations())
    # NetBox 4.x has thousands of operations; sanity-check we built a real tree
    assert count > 500, f"expected many operations, got {count}"


def test_two_segment_api_path_becomes_top_level_resource() -> None:
    """Spec gap fix: /api/search/, /api/status/ etc. should be present in the model."""
    loaded = _make_loaded_schema(
        path="/api/search/",
        method="get",
        operation_id="core_search",
        tags=["core"],
    )
    model = build_command_model(loaded)
    found = [
        (tag, resource, op)
        for tag, resource, op in model.iter_operations()
        if op.path == "/api/search/" and op.http_method is HttpMethod.GET
    ]
    assert len(found) == 1, f"expected 1 operation at /api/search/, got {len(found)}"
    tag, resource, op = found[0]
    assert tag == "core"
    assert resource == "search"
    assert op.operation_id == "core_search"


def test_two_segment_api_path_with_status_tag() -> None:
    """The tag from the spec (not derived from path) determines the model location."""
    loaded = _make_loaded_schema(
        path="/api/status/",
        method="get",
        operation_id="status_retrieve",
        tags=["status"],
    )
    model = build_command_model(loaded)
    found = [(t, r, o) for t, r, o in model.iter_operations() if o.path == "/api/status/"]
    assert len(found) == 1, f"expected 1 operation at /api/status/, got {len(found)}"
    assert found[0][0] == "status"
    assert found[0][1] == "status"
