"""writes.apply.resolve — single-record ResolvedRequest construction (Phase 3b)."""

from __future__ import annotations

from nsc.cli.writes.apply import ResolvedRequest, resolve
from nsc.cli.writes.input import RawWriteInput
from nsc.model.command_model import (
    FieldShape,
    HttpMethod,
    Operation,
    Parameter,
    ParameterLocation,
    PrimitiveType,
    RequestBodyShape,
)


def _create_op() -> Operation:
    return Operation(
        operation_id="dcim_devices_create",
        http_method=HttpMethod.POST,
        path="/api/dcim/devices/",
        request_body=RequestBodyShape(
            top_level="object_or_array",
            required=["name"],
            fields={
                "name": FieldShape(primitive=PrimitiveType.STRING),
                "count": FieldShape(primitive=PrimitiveType.INTEGER),
                "active": FieldShape(primitive=PrimitiveType.BOOLEAN),
            },
        ),
    )


def _update_op() -> Operation:
    return Operation(
        operation_id="dcim_devices_partial_update",
        http_method=HttpMethod.PATCH,
        path="/api/dcim/devices/{id}/",
        parameters=[
            Parameter(name="id", location=ParameterLocation.PATH, primitive=PrimitiveType.INTEGER)
        ],
        request_body=RequestBodyShape(
            top_level="object",
            fields={"status": FieldShape(primitive=PrimitiveType.STRING)},
        ),
    )


def _delete_op() -> Operation:
    return Operation(
        operation_id="dcim_devices_destroy",
        http_method=HttpMethod.DELETE,
        path="/api/dcim/devices/{id}/",
        parameters=[
            Parameter(name="id", location=ParameterLocation.PATH, primitive=PrimitiveType.INTEGER)
        ],
    )


def test_resolve_single_record_create() -> None:
    raw = RawWriteInput(records=[{"name": "rack-01"}], source="file")
    resolved = resolve(raw, _create_op(), path_vars={}, base_url="https://nb.example")
    assert len(resolved) == 1
    req = resolved[0]
    assert isinstance(req, ResolvedRequest)
    assert req.method is HttpMethod.POST
    assert req.url == "https://nb.example/api/dcim/devices/"
    assert req.body == {"name": "rack-01"}
    assert req.path_vars == {}
    assert req.record_indices == [0]
    assert req.operation_id == "dcim_devices_create"


def test_resolve_casts_string_int_to_int_for_integer_field() -> None:
    # `--field count=3` arrives as the string "3"; preflight validates it,
    # apply.resolve casts to int per FieldShape.
    raw = RawWriteInput(records=[{"name": "rack-01", "count": "3"}], source="fields_only")
    resolved = resolve(raw, _create_op(), path_vars={}, base_url="https://nb.example")
    body = resolved[0].body
    assert isinstance(body, dict)
    assert body["count"] == 3
    assert body["name"] == "rack-01"


def test_resolve_casts_string_bool_to_bool() -> None:
    raw = RawWriteInput(records=[{"name": "x", "active": "true"}], source="fields_only")
    resolved = resolve(raw, _create_op(), path_vars={}, base_url="https://nb.example")
    body = resolved[0].body
    assert isinstance(body, dict)
    assert body["active"] is True


def test_resolve_casts_string_bool_false() -> None:
    raw = RawWriteInput(records=[{"name": "x", "active": "no"}], source="fields_only")
    resolved = resolve(raw, _create_op(), path_vars={}, base_url="https://nb.example")
    body = resolved[0].body
    assert isinstance(body, dict)
    assert body["active"] is False


def test_resolve_update_with_path_var() -> None:
    raw = RawWriteInput(records=[{"status": "decommissioned"}], source="fields_only")
    resolved = resolve(raw, _update_op(), path_vars={"id": "42"}, base_url="https://nb.example")
    assert len(resolved) == 1
    req = resolved[0]
    assert req.method is HttpMethod.PATCH
    assert req.url == "https://nb.example/api/dcim/devices/42/"
    assert req.path_vars == {"id": "42"}
    assert req.body == {"status": "decommissioned"}


def test_resolve_delete_has_no_body() -> None:
    raw = RawWriteInput(records=[{}], source="fields_only")
    resolved = resolve(raw, _delete_op(), path_vars={"id": "42"}, base_url="https://nb.example")
    assert len(resolved) == 1
    req = resolved[0]
    assert req.method is HttpMethod.DELETE
    assert req.body is None
    assert req.url == "https://nb.example/api/dcim/devices/42/"


def test_resolve_url_strips_trailing_slash_from_base() -> None:
    raw = RawWriteInput(records=[{"name": "x"}], source="fields_only")
    resolved = resolve(raw, _create_op(), path_vars={}, base_url="https://nb.example/")
    assert resolved[0].url == "https://nb.example/api/dcim/devices/"


def test_resolve_redacts_authorization_in_visible_headers() -> None:
    raw = RawWriteInput(records=[{"name": "x"}], source="fields_only")
    resolved = resolve(
        raw,
        _create_op(),
        path_vars={},
        base_url="https://nb.example",
        headers={"Authorization": "Token secret", "Accept": "application/json"},
    )
    headers = resolved[0].headers
    assert headers["Authorization"] == "Token <redacted>"
    assert headers["Accept"] == "application/json"


def test_resolve_multi_record_one_request_per_record() -> None:
    # 3b only emits one-per-record. (3c routes bulk.)
    raw = RawWriteInput(
        records=[{"name": "a"}, {"name": "b"}], source="file", is_explicit_list=True
    )
    resolved = resolve(raw, _create_op(), path_vars={}, base_url="https://nb.example")
    assert len(resolved) == 2
    assert [r.body for r in resolved] == [{"name": "a"}, {"name": "b"}]
    assert [r.record_indices for r in resolved] == [[0], [1]]
