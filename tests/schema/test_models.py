"""Tests for OpenAPI subset Pydantic models."""

from __future__ import annotations

import json

from nsc.schema.models import OpenAPIDocument, ParameterIn

MINIMAL_DOC = {
    "openapi": "3.0.3",
    "info": {"title": "NetBox", "version": "4.1.0"},
    "paths": {
        "/api/dcim/devices/": {
            "get": {
                "operationId": "dcim_devices_list",
                "tags": ["dcim"],
                "parameters": [{"name": "name", "in": "query", "schema": {"type": "string"}}],
                "responses": {"200": {"description": "ok"}},
            },
            "post": {
                "operationId": "dcim_devices_create",
                "tags": ["dcim"],
                "responses": {"201": {"description": "created"}},
            },
        }
    },
    "components": {"schemas": {}},
    "tags": [{"name": "dcim"}],
}


def test_parses_minimal_document() -> None:
    doc = OpenAPIDocument.model_validate(MINIMAL_DOC)
    assert doc.info.title == "NetBox"
    assert doc.info.version == "4.1.0"
    assert "/api/dcim/devices/" in doc.paths


def test_path_item_exposes_operations_by_http_method() -> None:
    doc = OpenAPIDocument.model_validate(MINIMAL_DOC)
    item = doc.paths["/api/dcim/devices/"]
    assert item.get is not None
    assert item.get.operation_id == "dcim_devices_list"
    assert item.post is not None
    assert item.post.operation_id == "dcim_devices_create"


def test_parameters_use_in_enum() -> None:
    doc = OpenAPIDocument.model_validate(MINIMAL_DOC)
    item = doc.paths["/api/dcim/devices/"]
    assert item.get is not None
    assert item.get.parameters[0].in_ == ParameterIn.QUERY


def test_unknown_top_level_keys_are_tolerated() -> None:
    payload = {**MINIMAL_DOC, "x-vendor-extension": {"anything": True}}
    doc = OpenAPIDocument.model_validate(payload)
    # parses without raising; we don't expose the extension
    assert doc.info.title == "NetBox"


def test_round_trip_to_json_is_stable() -> None:
    doc = OpenAPIDocument.model_validate(MINIMAL_DOC)
    blob = doc.model_dump_json()
    again = OpenAPIDocument.model_validate(json.loads(blob))
    assert again.info.title == "NetBox"
