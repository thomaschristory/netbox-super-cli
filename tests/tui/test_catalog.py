from __future__ import annotations

from nsc.model.command_model import CommandModel, Operation, Resource, Tag
from nsc.tui.catalog import (
    ResourceRef,
    filter_resources,
    group_refs,
    grouped_resources,
    list_resources,
)


def _model() -> CommandModel:
    def res(name: str) -> Resource:
        return Resource(
            name=name,
            list_op=Operation(operation_id=f"{name}_list", http_method="GET", path=f"/api/{name}/"),
        )

    dcim = Tag(name="dcim", resources={"devices": res("devices"), "interfaces": res("interfaces")})
    ipam = Tag(name="ipam", resources={"prefixes": res("prefixes")})
    # a resource with no list_op must be skipped
    novel = Tag(name="x", resources={"noread": Resource(name="noread")})
    return CommandModel(
        info_title="t",
        info_version="1",
        schema_hash="h",
        tags={"dcim": dcim, "ipam": ipam, "x": novel},
    )


def test_list_resources_includes_only_listable_sorted() -> None:
    refs = list_resources(_model())
    assert [r.resource_name for r in refs] == ["devices", "interfaces", "prefixes"]
    assert all(isinstance(r, ResourceRef) for r in refs)


def test_list_resources_orders_by_tag_then_name_not_name_alone() -> None:
    # `aggregates` (ipam) sorts before `cables` (dcim) by name alone, but the
    # picker must group by tag first: all of dcim before any of ipam.
    dcim = Tag(
        name="dcim",
        resources={
            "cables": Resource(
                name="cables",
                list_op=Operation(operation_id="c", http_method="GET", path="/api/dcim/cables/"),
            )
        },
    )
    ipam = Tag(
        name="ipam",
        resources={
            "aggregates": Resource(
                name="aggregates",
                list_op=Operation(operation_id="a", http_method="GET", path="/api/ipam/aggs/"),
            )
        },
    )
    model = CommandModel(
        info_title="t", info_version="1", schema_hash="h", tags={"dcim": dcim, "ipam": ipam}
    )
    refs = list_resources(model)
    assert [(r.tag, r.resource_name) for r in refs] == [
        ("dcim", "cables"),
        ("ipam", "aggregates"),
    ]


def test_filter_resources_is_case_insensitive_substring() -> None:
    refs = list_resources(_model())
    assert [r.resource_name for r in filter_resources(refs, "iface")] == []
    assert [r.resource_name for r in filter_resources(refs, "INT")] == ["interfaces"]
    assert {r.resource_name for r in filter_resources(refs, "")} == {
        "devices",
        "interfaces",
        "prefixes",
    }


def test_resource_ref_label_combines_tag_and_name() -> None:
    refs = list_resources(_model())
    by_name = {r.resource_name: r for r in refs}
    assert by_name["prefixes"].label == "ipam / prefixes"


def test_grouped_resources_groups_by_tag_in_order_skipping_unlistable() -> None:
    groups = grouped_resources(_model())
    assert [(tag, [r.resource_name for r in refs]) for tag, refs in groups] == [
        ("dcim", ["devices", "interfaces"]),
        ("ipam", ["prefixes"]),
    ]


def test_group_refs_drops_emptied_groups_and_keeps_order() -> None:
    refs = filter_resources(list_resources(_model()), "face")  # only "interfaces" (dcim)
    groups = group_refs(refs)
    assert [(tag, [r.resource_name for r in g]) for tag, g in groups] == [
        ("dcim", ["interfaces"]),
    ]
