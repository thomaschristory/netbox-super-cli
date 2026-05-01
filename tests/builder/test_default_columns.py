from __future__ import annotations

from nsc.builder.build import build_command_model
from nsc.schema.loader import LoadedSchema
from nsc.schema.models import OpenAPIDocument


def _doc_with_list_op(record_props: dict[str, dict[str, str]]) -> OpenAPIDocument:
    return OpenAPIDocument.model_validate(
        {
            "openapi": "3.0.3",
            "info": {"title": "T", "version": "1.0.0"},
            "tags": [{"name": "dcim"}],
            "paths": {
                "/api/dcim/devices/": {
                    "get": {
                        "operationId": "dcim_devices_list",
                        "tags": ["dcim"],
                        "parameters": [],
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "count": {"type": "integer"},
                                                "next": {"type": "string"},
                                                "previous": {"type": "string"},
                                                "results": {
                                                    "type": "array",
                                                    "items": {
                                                        "type": "object",
                                                        "properties": record_props,
                                                    },
                                                },
                                            },
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
            "components": {"schemas": {}},
        }
    )


def _build(doc: OpenAPIDocument):
    loaded = LoadedSchema(document=doc, hash="testhash", source="memory", body=b"")
    model = build_command_model(loaded)
    return model.tags["dcim"].resources["devices"].list_op


def test_default_columns_includes_id_name_then_pads_with_scalars():
    doc = _doc_with_list_op(
        {
            "id": {"type": "integer"},
            "name": {"type": "string"},
            "url": {"type": "string"},
            "status": {"type": "string"},
            "extra": {"type": "string"},
        }
    )
    op = _build(doc)
    assert op is not None
    assert op.default_columns == ["id", "name", "url", "status", "extra"]


def test_default_columns_caps_at_six():
    props = {f"f{i}": {"type": "string"} for i in range(20)}
    props["id"] = {"type": "integer"}
    doc = _doc_with_list_op(props)
    op = _build(doc)
    assert op is not None
    assert len(op.default_columns) == 6
    assert "id" in op.default_columns


def test_default_columns_handles_slug_and_display_when_no_name():
    doc = _doc_with_list_op(
        {
            "id": {"type": "integer"},
            "slug": {"type": "string"},
            "display": {"type": "string"},
        }
    )
    op = _build(doc)
    assert op.default_columns == ["id", "slug", "display"]


def test_default_columns_skips_object_and_array_fields_during_padding():
    doc = _doc_with_list_op(
        {
            "id": {"type": "integer"},
            "name": {"type": "string"},
            "tags": {"type": "array"},
            "site": {"type": "object"},
            "model": {"type": "string"},
        }
    )
    op = _build(doc)
    # Padding skips array+object fields, so 'site' and 'tags' don't make the cut
    assert op.default_columns == ["id", "name", "model"]


def test_default_columns_resolves_ref_to_components_schemas():
    doc = OpenAPIDocument.model_validate(
        {
            "openapi": "3.0.3",
            "info": {"title": "T", "version": "1.0.0"},
            "tags": [{"name": "dcim"}],
            "paths": {
                "/api/dcim/devices/": {
                    "get": {
                        "operationId": "dcim_devices_list",
                        "tags": ["dcim"],
                        "parameters": [],
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "results": {
                                                    "type": "array",
                                                    "items": {
                                                        "$ref": "#/components/schemas/Device"
                                                    },
                                                }
                                            },
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
            "components": {
                "schemas": {
                    "Device": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "name": {"type": "string"},
                            "status": {"type": "string"},
                        },
                    }
                }
            },
        }
    )
    op = _build(doc)
    assert op.default_columns == ["id", "name", "status"]


def test_default_columns_is_none_when_response_has_no_recognizable_shape():
    doc = OpenAPIDocument.model_validate(
        {
            "openapi": "3.0.3",
            "info": {"title": "T", "version": "1.0.0"},
            "tags": [{"name": "dcim"}],
            "paths": {
                "/api/dcim/devices/": {
                    "get": {
                        "operationId": "dcim_devices_list",
                        "tags": ["dcim"],
                        "parameters": [],
                        "responses": {"200": {"description": "ok", "content": {}}},
                    }
                }
            },
            "components": {"schemas": {}},
        }
    )
    op = _build(doc)
    assert op.default_columns is None


def test_default_columns_for_get_uses_response_schema_directly_not_results():
    doc = OpenAPIDocument.model_validate(
        {
            "openapi": "3.0.3",
            "info": {"title": "T", "version": "1.0.0"},
            "tags": [{"name": "dcim"}],
            "paths": {
                "/api/dcim/devices/{id}/": {
                    "get": {
                        "operationId": "dcim_devices_retrieve",
                        "tags": ["dcim"],
                        "parameters": [
                            {
                                "name": "id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "integer"},
                            }
                        ],
                        "responses": {
                            "200": {
                                "description": "ok",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "id": {"type": "integer"},
                                                "name": {"type": "string"},
                                                "serial": {"type": "string"},
                                            },
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
            "components": {"schemas": {}},
        }
    )
    loaded = LoadedSchema(document=doc, hash="h", source="m", body=b"")
    model = build_command_model(loaded)
    op = model.tags["dcim"].resources["devices"].get_op
    assert op is not None
    assert op.default_columns == ["id", "name", "serial"]
