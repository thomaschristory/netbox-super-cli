from __future__ import annotations

from nsc.model.command_model import (
    CommandModel,
    Operation,
    Parameter,
    ParameterLocation,
    Resource,
    Tag,
)
from nsc.tui.relations import related_views, singularize


def _qp(name: str) -> Parameter:
    return Parameter(name=name, location=ParameterLocation.QUERY)


def _model() -> CommandModel:
    interfaces = Resource(
        name="interfaces",
        list_op=Operation(
            operation_id="dcim_interfaces_list",
            http_method="GET",
            path="/api/dcim/interfaces/",
            parameters=[_qp("device_id"), _qp("name")],
        ),
    )
    devices = Resource(
        name="devices",
        list_op=Operation(
            operation_id="dcim_devices_list",
            http_method="GET",
            path="/api/dcim/devices/",
            parameters=[_qp("site_id")],
        ),
    )
    tag = Tag(name="dcim", resources={"devices": devices, "interfaces": interfaces})
    return CommandModel(info_title="t", info_version="1", schema_hash="h", tags={"dcim": tag})


def test_singularize_common_cases() -> None:
    assert singularize("devices") == "device"
    assert singularize("interfaces") == "interface"
    assert singularize("ip-addresses") == "ip-address"
    assert singularize("vlans") == "vlan"


def test_related_views_finds_resources_filtering_on_this_resource() -> None:
    views = related_views(_model(), "devices")
    assert len(views) == 1
    v = views[0]
    assert v.resource_name == "interfaces"
    assert v.filter_param == "device_id"
    assert v.list_op.path == "/api/dcim/interfaces/"


def test_related_views_empty_when_nothing_references_it() -> None:
    assert related_views(_model(), "interfaces") == []
