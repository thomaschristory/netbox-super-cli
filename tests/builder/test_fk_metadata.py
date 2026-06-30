"""Schema-driven foreign-key target metadata.

NetBox types a writable FK as ``oneOf[integer, Brief<X>Request]``. The builder
records the target serializer name (``<X>``) on the field and indexes which
resource serves objects of each serializer, so the TUI can resolve an FK picker
to the true target even when the field name does not match the resource name
(e.g. a virtual-machine's ``role`` targets dcim ``device-roles``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nsc.builder.build import build_command_model
from nsc.model.command_model import MODEL_FORMAT_VERSION, FkResourceRef
from nsc.schema.loader import LoadedSchema, load_schema
from nsc.schema.models import OpenAPIDocument

_BUNDLED = Path("nsc/schemas/bundled/netbox-4.6.0.json.gz")


@pytest.fixture(scope="module")
def bundled_model():
    return build_command_model(load_schema(str(_BUNDLED)))


def test_fk_resources_index_maps_serializer_to_resource(bundled_model) -> None:
    index = bundled_model.fk_resources
    assert index["DeviceRole"] == FkResourceRef(tag="dcim", resource="device-roles")
    assert index["ContactRole"] == FkResourceRef(tag="tenancy", resource="contact-roles")
    assert index["InventoryItemRole"] == FkResourceRef(tag="dcim", resource="inventory-item-roles")
    assert index["Role"] == FkResourceRef(tag="ipam", resource="roles")


def test_field_fk_target_records_serializer_name(bundled_model) -> None:
    devices = bundled_model.tags["dcim"].resources["devices"]
    assert devices.create_op is not None
    assert devices.create_op.request_body is not None
    assert devices.create_op.request_body.fields["role"].fk_target == "DeviceRole"

    vms = bundled_model.tags["virtualization"].resources["virtual-machines"]
    assert vms.create_op is not None
    assert vms.create_op.request_body is not None
    # A VM's role is a device-role, despite the field/resource name mismatch.
    assert vms.create_op.request_body.fields["role"].fk_target == "DeviceRole"


def test_every_fk_target_resolves_in_index(bundled_model) -> None:
    # Invariant: a field's declared FK target must exist in the index, or the TUI
    # picker silently degrades to raw-ID entry. Catches list serializers whose
    # name (e.g. DeviceWithConfigContext) doesn't normalize to the brief base.
    index = bundled_model.fk_resources
    missing: set[str] = set()
    for _tag, _resource, op in bundled_model.iter_operations():
        if op.request_body is None:
            continue
        for shape in op.request_body.fields.values():
            if shape.fk_target is not None and shape.fk_target not in index:
                missing.add(shape.fk_target)
    assert not missing, f"FK targets with no resource in the index: {sorted(missing)}"


def test_with_config_context_targets_resolve(bundled_model) -> None:
    # Device/VirtualMachine list serializers carry a WithConfigContext suffix;
    # the index must still key them under the brief base name.
    index = bundled_model.fk_resources
    assert index["Device"] == FkResourceRef(tag="dcim", resource="devices")
    assert index["VirtualMachine"] == FkResourceRef(
        tag="virtualization", resource="virtual-machines"
    )


def test_non_fk_field_has_no_fk_target(bundled_model) -> None:
    devices = bundled_model.tags["dcim"].resources["devices"]
    assert devices.create_op is not None
    assert devices.create_op.request_body is not None
    assert devices.create_op.request_body.fields["name"].fk_target is None


def test_builder_stamps_current_format_version(bundled_model) -> None:
    assert bundled_model.format_version == MODEL_FORMAT_VERSION


def _loaded(doc: OpenAPIDocument) -> LoadedSchema:
    return LoadedSchema(source="test", body=b"", hash="sha256:test", document=doc)


def _doc(body_role: dict[str, Any]) -> OpenAPIDocument:
    return OpenAPIDocument.model_validate(
        {
            "openapi": "3.0.0",
            "info": {"title": "T", "version": "0"},
            "paths": {
                "/api/t/widgets/": {
                    "post": {
                        "operationId": "create",
                        "tags": ["t"],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"role": body_role},
                                    }
                                }
                            }
                        },
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
            "tags": [{"name": "t"}],
        }
    )


def test_fk_target_extracted_from_plain_oneof() -> None:
    doc = _doc({"oneOf": [{"type": "integer"}, {"$ref": "#/components/schemas/BriefThingRequest"}]})
    model = build_command_model(_loaded(doc))
    field = model.tags["t"].resources["widgets"].create_op.request_body.fields["role"]
    assert field.fk_target == "Thing"


def test_fk_target_extracted_from_nullable_allof_wrapper() -> None:
    # NetBox wraps a nullable FK as oneOf[integer, {allOf:[$ref], nullable}].
    doc = _doc(
        {
            "oneOf": [
                {"type": "integer"},
                {"allOf": [{"$ref": "#/components/schemas/BriefThingRequest"}], "nullable": True},
            ],
            "nullable": True,
        }
    )
    model = build_command_model(_loaded(doc))
    field = model.tags["t"].resources["widgets"].create_op.request_body.fields["role"]
    assert field.fk_target == "Thing"


def test_string_enum_role_is_not_an_fk() -> None:
    # Some `role` fields (e.g. ip-addresses) are plain string enums, not FKs.
    doc = _doc({"type": "string", "enum": ["loopback", "secondary"]})
    model = build_command_model(_loaded(doc))
    field = model.tags["t"].resources["widgets"].create_op.request_body.fields["role"]
    assert field.fk_target is None
