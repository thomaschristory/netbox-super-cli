from __future__ import annotations

from nsc.model.command_model import (
    CommandModel,
    Operation,
    Resource,
    Tag,
)
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


def test_fk_target_is_frozen() -> None:
    target = resolve_fk_target("site", None, _model())
    try:
        target.kind = "raw_id"  # type: ignore[misc]
    except (AttributeError, TypeError, ValueError):
        return
    raise AssertionError("FkTarget should be immutable")
