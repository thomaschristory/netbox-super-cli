"""Tests for the schema → CommandModel builder."""

from __future__ import annotations

from pathlib import Path

import pytest

from nsc.builder.build import build_command_model
from nsc.model.command_model import HttpMethod, ParameterLocation
from nsc.schema.loader import load_schema


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
