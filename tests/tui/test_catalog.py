from __future__ import annotations

from nsc.model.command_model import CommandModel, Operation, Resource, Tag
from nsc.tui.catalog import ResourceRef, filter_resources, list_resources


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
