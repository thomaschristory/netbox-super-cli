"""RequestBodyShape and FieldShape on Operation (Phase 3a)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nsc.model.command_model import (
    FieldShape,
    HttpMethod,
    Operation,
    PrimitiveType,
    RequestBodyShape,
)


def test_field_shape_minimal() -> None:
    fs = FieldShape(primitive=PrimitiveType.STRING)
    assert fs.primitive is PrimitiveType.STRING
    assert fs.enum is None
    assert fs.nullable is False


def test_field_shape_with_enum_and_nullable() -> None:
    fs = FieldShape(primitive=PrimitiveType.STRING, enum=["a", "b"], nullable=True)
    assert fs.enum == ["a", "b"]
    assert fs.nullable is True


def test_request_body_shape_top_level_object() -> None:
    rbs = RequestBodyShape(
        top_level="object",
        required=["name"],
        fields={"name": FieldShape(primitive=PrimitiveType.STRING)},
    )
    assert rbs.top_level == "object"
    assert rbs.required == ["name"]
    assert rbs.fields["name"].primitive is PrimitiveType.STRING


def test_request_body_shape_top_level_array() -> None:
    rbs = RequestBodyShape(top_level="array")
    assert rbs.top_level == "array"
    assert rbs.required == []
    assert rbs.fields == {}


def test_request_body_shape_top_level_object_or_array() -> None:
    rbs = RequestBodyShape(top_level="object_or_array")
    assert rbs.top_level == "object_or_array"


def test_request_body_shape_rejects_unknown_top_level() -> None:
    with pytest.raises(ValidationError):
        RequestBodyShape(top_level="unknown")  # type: ignore[arg-type]


def test_operation_request_body_optional_default_none() -> None:
    op = Operation(
        operation_id="dcim_devices_list",
        http_method=HttpMethod.GET,
        path="/api/dcim/devices/",
    )
    assert op.request_body is None


def test_operation_request_body_attached() -> None:
    rbs = RequestBodyShape(
        top_level="object",
        required=["name"],
        fields={"name": FieldShape(primitive=PrimitiveType.STRING)},
    )
    op = Operation(
        operation_id="dcim_devices_create",
        http_method=HttpMethod.POST,
        path="/api/dcim/devices/",
        request_body=rbs,
    )
    assert op.request_body is rbs


def test_operation_frozen() -> None:
    op = Operation(
        operation_id="dcim_devices_list",
        http_method=HttpMethod.GET,
        path="/api/dcim/devices/",
    )
    with pytest.raises(ValidationError):
        op.request_body = RequestBodyShape(top_level="object")  # type: ignore[misc]
