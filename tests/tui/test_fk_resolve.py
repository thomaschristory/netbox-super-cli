from __future__ import annotations

import pytest

from nsc.builder.build import build_command_model
from nsc.model.command_model import (
    CommandModel,
    Operation,
    Resource,
    Tag,
)
from nsc.schema.loader import load_schema
from nsc.tui.fk import FkTarget, resolve_fk_target


def _model() -> CommandModel:
    sites = Resource(
        name="sites",
        list_op=Operation(
            operation_id="dcim_sites_list",
            http_method="GET",
            path="/api/dcim/sites/",
        ),
    )
    devices = Resource(
        name="devices",
        list_op=Operation(
            operation_id="dcim_devices_list",
            http_method="GET",
            path="/api/dcim/devices/",
        ),
    )
    prefixes = Resource(
        name="prefixes",
        list_op=Operation(
            operation_id="ipam_prefixes_list",
            http_method="GET",
            path="/api/ipam/prefixes/",
        ),
    )
    dcim = Tag(name="dcim", resources={"sites": sites, "devices": devices})
    ipam = Tag(name="ipam", resources={"prefixes": prefixes})
    return CommandModel(
        info_title="t",
        info_version="1",
        schema_hash="h",
        tags={"dcim": dcim, "ipam": ipam},
    )


def test_resolve_from_nested_url_trailing_slash() -> None:
    value = {"id": 3, "url": "https://nb/api/dcim/sites/3/", "name": "HQ"}
    target = resolve_fk_target("site", value, _model())
    assert isinstance(target, FkTarget)
    assert target.kind == "picker"
    assert target.resource_name == "sites"
    assert target.tag == "dcim"
    assert target.list_op is not None
    assert target.list_op.path == "/api/dcim/sites/"
    assert target.current_id == 3


def test_resolve_from_nested_url_no_trailing_slash() -> None:
    value = {"id": 7, "url": "https://nb/api/dcim/sites/7"}
    target = resolve_fk_target("site", value, _model())
    assert target.kind == "picker"
    assert target.resource_name == "sites"
    assert target.current_id == 7


def test_resolve_from_nested_url_prefixes_es_plural() -> None:
    value = {"id": 12, "url": "https://nb/api/ipam/prefixes/12/"}
    target = resolve_fk_target("prefix", value, _model())
    assert target.kind == "picker"
    assert target.resource_name == "prefixes"
    assert target.tag == "ipam"
    assert target.current_id == 12


def test_resolve_by_field_name_no_value() -> None:
    target = resolve_fk_target("site", None, _model())
    assert target.kind == "picker"
    assert target.resource_name == "sites"
    assert target.tag == "dcim"
    assert target.current_id is None


def test_resolve_by_field_name_id_suffix() -> None:
    target = resolve_fk_target("site_id", None, _model())
    assert target.kind == "picker"
    assert target.resource_name == "sites"
    assert target.current_id is None


def test_resolve_by_field_name_es_plural() -> None:
    target = resolve_fk_target("prefix_id", None, _model())
    assert target.kind == "picker"
    assert target.resource_name == "prefixes"
    assert target.tag == "ipam"


def test_unknown_url_resource_falls_back_to_raw_id() -> None:
    value = {"id": 5, "url": "https://nb/api/dcim/widgets/5/"}
    target = resolve_fk_target("widget", value, _model())
    assert target.kind == "raw_id"
    assert target.resource_name is None
    assert target.list_op is None
    assert target.hint
    assert "widget" in target.hint


def test_url_resource_without_list_op_falls_back_to_raw_id() -> None:
    # The resource exists but has no list endpoint, so a chooser is impossible;
    # `kind="picker"` must never carry a None list_op (it would be a dead button).
    sites = Resource(name="sites", list_op=None)
    dcim = Tag(name="dcim", resources={"sites": sites})
    model = CommandModel(info_title="t", info_version="1", schema_hash="h", tags={"dcim": dcim})
    value = {"id": 3, "url": "https://nb/api/dcim/sites/3/"}
    target = resolve_fk_target("site", value, model)
    assert target.kind == "raw_id"
    assert target.list_op is None
    assert target.current_id == 3
    assert target.hint


def test_unknown_field_name_falls_back_to_raw_id() -> None:
    target = resolve_fk_target("gizmo_id", None, _model())
    assert target.kind == "raw_id"
    assert target.resource_name is None
    assert target.hint
    assert "gizmo" in target.hint


def test_url_path_takes_priority_and_carries_current_id() -> None:
    value = {"id": 9, "url": "https://nb/api/dcim/devices/9/"}
    target = resolve_fk_target("site", value, _model())
    assert target.kind == "picker"
    assert target.resource_name == "devices"
    assert target.current_id == 9


def _roles_model() -> CommandModel:
    """A model reproducing NetBox's cross-tag ``role`` collision: ipam exposes a
    bare ``roles`` resource (singularizes to ``role``) while dcim names its role
    targets ``<owner>-roles`` (``device-roles``, ``rack-roles``)."""

    def _tag(name: str, resources: list[str]) -> Tag:
        out: dict[str, Resource] = {}
        for res in resources:
            op = Operation(
                operation_id=f"{name}_{res.replace('-', '_')}_list",
                http_method="GET",
                path=f"/api/{name}/{res}/",
            )
            out[res] = Resource(name=res, list_op=op)
        return Tag(name=name, resources=out)

    return CommandModel(
        info_title="t",
        info_version="1",
        schema_hash="h",
        tags={
            "dcim": _tag("dcim", ["devices", "racks", "device-roles", "rack-roles"]),
            "ipam": _tag("ipam", ["prefixes", "roles"]),
        },
    )


def test_role_filter_on_devices_resolves_device_roles_not_ipam_roles() -> None:
    # The bug: filtering devices by `role` opened the ipam `roles` picker because
    # `device-roles` does not singularize to `role`. With the device context, the
    # qualified candidate `device-role` must win.
    target = resolve_fk_target(
        "role", None, _roles_model(), context_tag="dcim", context_resource="devices"
    )
    assert target.kind == "picker"
    assert target.tag == "dcim"
    assert target.resource_name == "device-roles"
    assert target.list_op is not None
    assert target.list_op.path == "/api/dcim/device-roles/"


def test_role_filter_on_racks_resolves_rack_roles_not_device_roles() -> None:
    # Precision: a plain endswith('-role') match would pick `device-roles`
    # (sorted first); the qualified candidate `rack-role` must target rack-roles.
    target = resolve_fk_target(
        "role", None, _roles_model(), context_tag="dcim", context_resource="racks"
    )
    assert target.kind == "picker"
    assert target.resource_name == "rack-roles"
    assert target.list_op is not None
    assert target.list_op.path == "/api/dcim/rack-roles/"


def test_role_filter_on_prefixes_still_resolves_ipam_roles() -> None:
    # Regression guard: ipam resources whose `role` genuinely targets ipam roles
    # must keep resolving there (no dcim qualified candidate exists for them).
    target = resolve_fk_target(
        "role", None, _roles_model(), context_tag="ipam", context_resource="prefixes"
    )
    assert target.kind == "picker"
    assert target.tag == "ipam"
    assert target.resource_name == "roles"
    assert target.list_op is not None
    assert target.list_op.path == "/api/ipam/roles/"


def test_role_id_on_devices_resolves_device_roles() -> None:
    target = resolve_fk_target(
        "role_id", None, _roles_model(), context_tag="dcim", context_resource="devices"
    )
    assert target.kind == "picker"
    assert target.resource_name == "device-roles"


def test_context_free_resolution_unchanged() -> None:
    # Without context, behavior is the pre-fix global scan (used by call sites
    # that pass no context): a bare `role` still resolves to ipam `roles`.
    target = resolve_fk_target("role", None, _roles_model())
    assert target.kind == "picker"
    assert target.resource_name == "roles"
    assert target.tag == "ipam"


def test_non_colliding_field_resolves_with_context() -> None:
    # A field with no qualified candidate (`device-site` does not exist) falls
    # through to the bare-name match, scoped to the context tag first.
    target = resolve_fk_target(
        "site_id", None, _model(), context_tag="dcim", context_resource="devices"
    )
    assert target.kind == "picker"
    assert target.resource_name == "sites"
    assert target.tag == "dcim"


@pytest.fixture(scope="module")
def bundled_model() -> CommandModel:
    return build_command_model(load_schema("nsc/schemas/bundled/netbox-4.6.0.json.gz"))


@pytest.mark.parametrize(
    ("tag", "resource", "want_tag", "want_resource"),
    [
        # The reported #139 case and its name-aligned siblings.
        ("dcim", "devices", "dcim", "device-roles"),
        ("dcim", "racks", "dcim", "rack-roles"),
        ("dcim", "inventory-items", "dcim", "inventory-item-roles"),
        # Name-MISALIGNED FKs: only the schema-driven target resolves these.
        ("virtualization", "virtual-machines", "dcim", "device-roles"),
        ("tenancy", "contact-assignments", "tenancy", "contact-roles"),
        ("dcim", "inventory-item-templates", "dcim", "inventory-item-roles"),
        # Genuinely-ipam role FKs stay put.
        ("ipam", "prefixes", "ipam", "roles"),
        ("ipam", "vlans", "ipam", "roles"),
    ],
)
def test_role_resolves_to_true_target_across_resources(
    bundled_model: CommandModel, tag: str, resource: str, want_tag: str, want_resource: str
) -> None:
    target = resolve_fk_target(
        "role", None, bundled_model, context_tag=tag, context_resource=resource
    )
    assert target.kind == "picker", f"{tag}/{resource} role did not resolve to a picker"
    assert (target.tag, target.resource_name) == (want_tag, want_resource)


@pytest.mark.parametrize(
    ("field", "tag", "resource", "want_tag", "want_resource"),
    [
        # FKs to Device / VirtualMachine, whose list serializers carry a
        # WithConfigContext suffix and whose field names don't singularize to the
        # resource — only the schema-driven target resolves these to a picker.
        ("installed_device", "dcim", "device-bays", "dcim", "devices"),
        ("virtual_machine", "virtualization", "interfaces", "virtualization", "virtual-machines"),
        (
            "virtual_machine",
            "virtualization",
            "virtual-disks",
            "virtualization",
            "virtual-machines",
        ),
    ],
)
def test_with_config_context_fk_resolves_to_picker(
    bundled_model: CommandModel,
    field: str,
    tag: str,
    resource: str,
    want_tag: str,
    want_resource: str,
) -> None:
    target = resolve_fk_target(
        field, None, bundled_model, context_tag=tag, context_resource=resource
    )
    assert target.kind == "picker", f"{tag}/{resource}.{field} fell back to raw-ID"
    assert (target.tag, target.resource_name) == (want_tag, want_resource)


def test_fk_target_is_frozen() -> None:
    target = resolve_fk_target("site", None, _model())
    try:
        target.kind = "raw_id"  # type: ignore[misc]
    except (AttributeError, TypeError, ValueError):
        return
    raise AssertionError("FkTarget should be immutable")
