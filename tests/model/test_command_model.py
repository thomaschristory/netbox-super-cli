"""Tests for the framework-free command-model."""

from __future__ import annotations

import json

from nsc.model.command_model import (
    CommandModel,
    HttpMethod,
    Operation,
    Parameter,
    ParameterLocation,
    PrimitiveType,
    Resource,
    Tag,
)


def _sample_model() -> CommandModel:
    op = Operation(
        operation_id="dcim_devices_list",
        http_method=HttpMethod.GET,
        path="/api/dcim/devices/",
        summary="List devices",
        parameters=[
            Parameter(
                name="name",
                location=ParameterLocation.QUERY,
                primitive=PrimitiveType.STRING,
                required=False,
                description="Filter by name",
            )
        ],
    )
    res = Resource(name="devices", list_op=op)
    return CommandModel(
        info_title="NetBox",
        info_version="4.1.0",
        schema_hash="a" * 64,
        tags={"dcim": Tag(name="dcim", resources={"devices": res})},
    )


def test_constructs_a_minimal_model() -> None:
    m = _sample_model()
    assert m.info_version == "4.1.0"
    assert "dcim" in m.tags
    assert "devices" in m.tags["dcim"].resources


def test_round_trips_through_json() -> None:
    m = _sample_model()
    blob = m.model_dump_json()
    again = CommandModel.model_validate(json.loads(blob))
    assert again == m


def test_resource_lists_known_verbs() -> None:
    m = _sample_model()
    res = m.tags["dcim"].resources["devices"]
    assert res.list_op is not None
    assert res.list_op.http_method == HttpMethod.GET
    assert res.get_op is None  # not provided in sample
    assert res.custom_actions == []


def test_iter_all_operations_walks_the_tree() -> None:
    m = _sample_model()
    ops = list(m.iter_operations())
    assert len(ops) == 1
    tag, resource, op = ops[0]
    assert tag == "dcim"
    assert resource == "devices"
    assert op.operation_id == "dcim_devices_list"


def test_operation_has_optional_default_columns_field_defaulting_to_none() -> None:
    op = Operation(
        operation_id="dcim_devices_list",
        http_method=HttpMethod.GET,
        path="/api/dcim/devices/",
    )
    assert op.default_columns is None


def test_operation_round_trips_default_columns_through_json() -> None:
    op = Operation(
        operation_id="dcim_devices_list",
        http_method=HttpMethod.GET,
        path="/api/dcim/devices/",
        default_columns=["id", "name", "site"],
    )
    payload = op.model_dump_json()
    restored = Operation.model_validate_json(payload)
    assert restored.default_columns == ["id", "name", "site"]
