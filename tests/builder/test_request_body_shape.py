"""Builder bridges schema RequestBody → model RequestBodyShape (Phase 3a)."""

from __future__ import annotations

from nsc.builder.build import build_command_model
from nsc.model.command_model import HttpMethod, PrimitiveType
from nsc.schema.loader import LoadedSchema
from nsc.schema.models import (
    Components,
    Info,
    MediaType,
    OpenAPIDocument,
    Operation,
    PathItem,
    RequestBody,
    Response,
    SchemaObject,
)


def _doc_with_post(request_schema: SchemaObject) -> OpenAPIDocument:
    response_ok = Response(
        description="ok",
        content={"application/json": MediaType(schema_=SchemaObject(type="object"))},
    )
    op = Operation(
        operation_id="dcim_devices_create",
        tags=["dcim"],
        responses={"201": response_ok},
        request_body=RequestBody(
            content={"application/json": MediaType(schema_=request_schema)},
        ),
    )
    return OpenAPIDocument(
        openapi="3.0.3",
        info=Info(title="t", version="v"),
        paths={"/api/dcim/devices/": PathItem(post=op)},
        components=Components(),
    )


def _build(doc: OpenAPIDocument):
    loaded = LoadedSchema(document=doc, hash="x", source="memory", body=b"")
    return build_command_model(loaded)


def _find_op(model, operation_id):
    for _, _, op in model.iter_operations():
        if op.operation_id == operation_id:
            return op
    raise AssertionError(f"operation {operation_id!r} not built")


def test_request_body_object_with_required_and_primitive_fields() -> None:
    schema = SchemaObject(
        type="object",
        required=["name"],
        properties={
            "name": SchemaObject(type="string"),
            "count": SchemaObject(type="integer"),
            "active": SchemaObject(type="boolean"),
        },
    )
    model = _build(_doc_with_post(schema))
    op = _find_op(model, "dcim_devices_create")
    assert op.http_method is HttpMethod.POST
    assert op.request_body is not None
    assert op.request_body.top_level == "object"
    assert op.request_body.required == ["name"]
    assert op.request_body.fields["name"].primitive is PrimitiveType.STRING
    assert op.request_body.fields["count"].primitive is PrimitiveType.INTEGER
    assert op.request_body.fields["active"].primitive is PrimitiveType.BOOLEAN


def test_request_body_field_with_enum() -> None:
    schema = SchemaObject(
        type="object",
        properties={"status": SchemaObject(type="string", enum=["active", "planned"])},
    )
    model = _build(_doc_with_post(schema))
    op = _find_op(model, "dcim_devices_create")
    assert op.request_body is not None
    assert op.request_body.fields["status"].enum == ["active", "planned"]


def test_request_body_top_level_array() -> None:
    schema = SchemaObject(type="array", items=SchemaObject(type="object"))
    model = _build(_doc_with_post(schema))
    op = _find_op(model, "dcim_devices_create")
    assert op.request_body is not None
    assert op.request_body.top_level == "array"
    assert op.request_body.required == []
    assert op.request_body.fields == {}


def test_request_body_one_of_object_or_array_yields_object_or_array_top_level() -> None:
    schema = SchemaObject.model_validate(
        {
            "oneOf": [
                {"type": "object", "properties": {"name": {"type": "string"}}},
                {"type": "array", "items": {"type": "object"}},
            ]
        }
    )
    model = _build(_doc_with_post(schema))
    op = _find_op(model, "dcim_devices_create")
    assert op.request_body is not None
    assert op.request_body.top_level == "object_or_array"


def test_request_body_unparseable_yields_none() -> None:
    schema = SchemaObject()
    model = _build(_doc_with_post(schema))
    op = _find_op(model, "dcim_devices_create")
    assert op.request_body is None


def test_get_operation_has_no_request_body() -> None:
    response_ok = Response(
        description="ok",
        content={"application/json": MediaType(schema_=SchemaObject(type="object"))},
    )
    op = Operation(
        operation_id="dcim_devices_list",
        tags=["dcim"],
        responses={"200": response_ok},
    )
    doc = OpenAPIDocument(
        openapi="3.0.3",
        info=Info(title="t", version="v"),
        paths={"/api/dcim/devices/": PathItem(get=op)},
        components=Components(),
    )
    model = _build(doc)
    built = _find_op(model, "dcim_devices_list")
    assert built.request_body is None


def test_request_body_one_of_with_ref_object_and_inline_array_yields_object_or_array() -> None:
    # NetBox's actual create-endpoint shape: a $ref to the writable request
    # schema OR an inline array of the same.
    schema = SchemaObject.model_validate(
        {
            "oneOf": [
                {"$ref": "#/components/schemas/WritableThing"},
                {"type": "array", "items": {"$ref": "#/components/schemas/WritableThing"}},
            ]
        }
    )
    components = Components(
        schemas={
            "WritableThing": SchemaObject(
                type="object",
                required=["name"],
                properties={
                    "name": SchemaObject(type="string"),
                    "status": SchemaObject(type="string", enum=["active", "planned"]),
                },
            )
        }
    )
    response_ok = Response(
        description="ok",
        content={"application/json": MediaType(schema_=SchemaObject(type="object"))},
    )
    op = Operation(
        operation_id="dcim_devices_create",
        tags=["dcim"],
        responses={"201": response_ok},
        request_body=RequestBody(
            content={"application/json": MediaType(schema_=schema)},
        ),
    )
    doc = OpenAPIDocument(
        openapi="3.0.3",
        info=Info(title="t", version="v"),
        paths={"/api/dcim/devices/": PathItem(post=op)},
        components=components,
    )

    model = _build(doc)
    built = _find_op(model, "dcim_devices_create")
    assert built.request_body is not None
    assert built.request_body.top_level == "object_or_array"
    assert built.request_body.required == ["name"]
    assert built.request_body.fields["name"].primitive is PrimitiveType.STRING
    assert built.request_body.fields["status"].enum == ["active", "planned"]


def test_request_body_one_of_with_only_ref_object_branch_is_object() -> None:
    schema = SchemaObject.model_validate(
        {"oneOf": [{"$ref": "#/components/schemas/WritableThing"}]}
    )
    components = Components(
        schemas={
            "WritableThing": SchemaObject(
                type="object",
                required=["name"],
                properties={"name": SchemaObject(type="string")},
            )
        }
    )
    response_ok = Response(
        description="ok",
        content={"application/json": MediaType(schema_=SchemaObject(type="object"))},
    )
    op = Operation(
        operation_id="x_create",
        tags=["x"],
        responses={"201": response_ok},
        request_body=RequestBody(
            content={"application/json": MediaType(schema_=schema)},
        ),
    )
    doc = OpenAPIDocument(
        openapi="3.0.3",
        info=Info(title="t", version="v"),
        paths={"/api/x/things/": PathItem(post=op)},
        components=components,
    )

    model = _build(doc)
    built = _find_op(model, "x_create")
    assert built.request_body is not None
    assert built.request_body.top_level == "object"
    assert built.request_body.required == ["name"]
    assert built.request_body.fields["name"].primitive is PrimitiveType.STRING
