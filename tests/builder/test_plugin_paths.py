"""Plugin endpoints get one resource per `/api/plugins/<plugin>/<resource>/` path (#202)."""

from __future__ import annotations

import json
from typing import Any

from nsc.builder.build import build_command_model
from nsc.model.command_model import CommandModel, FkResourceRef
from nsc.schema.hashing import canonical_sha256
from nsc.schema.loader import LoadedSchema
from nsc.schema.models import OpenAPIDocument


def _op(operation_id: str, tag: str) -> dict[str, Any]:
    return {"operationId": operation_id, "tags": [tag], "responses": {"200": {"description": "OK"}}}


def _build(paths: dict[str, dict[str, Any]]) -> CommandModel:
    doc_dict: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {"title": "Test", "version": "0.0.1"},
        "paths": paths,
    }
    body = json.dumps(doc_dict).encode()
    doc = OpenAPIDocument.model_validate(doc_dict)
    loaded = LoadedSchema(source="<test>", body=body, hash=canonical_sha256(body), document=doc)
    return build_command_model(loaded)


def _branching_paths(tag: str = "plugins") -> dict[str, dict[str, Any]]:
    # Shape of netbox-branching 1.2 on NetBox 4.7: every path is tagged `plugins`.
    base = "/api/plugins/branching"
    return {
        f"{base}/branches/": {
            "get": _op("plugins_branching_branches_list", tag),
            "post": _op("plugins_branching_branches_create", tag),
        },
        f"{base}/branches/{{id}}/": {
            "get": _op("plugins_branching_branches_retrieve", tag),
            "patch": _op("plugins_branching_branches_partial_update", tag),
            "delete": _op("plugins_branching_branches_destroy", tag),
        },
        f"{base}/branches/{{id}}/merge/": {
            "post": _op("plugins_branching_branches_merge_create", tag)
        },
        f"{base}/changes/": {"get": _op("plugins_branching_changes_list", tag)},
        f"{base}/changes/{{id}}/": {"get": _op("plugins_branching_changes_retrieve", tag)},
        f"{base}/branch-events/": {"get": _op("plugins_branching_branch_events_list", tag)},
        f"{base}/branchable-models/": {"get": _op("plugins_branching_branchable_models_list", tag)},
    }


def test_generic_plugins_tag_becomes_the_plugin_name() -> None:
    model = _build(_branching_paths())
    assert "plugins" not in model.tags
    assert set(model.tags["branching"].resources) == {
        "branches",
        "changes",
        "branch-events",
        "branchable-models",
    }


def test_plugin_resources_keep_their_own_operations() -> None:
    resources = _build(_branching_paths()).tags["branching"].resources
    branches = resources["branches"]
    assert branches.list_op is not None
    assert branches.list_op.path == "/api/plugins/branching/branches/"
    assert branches.create_op is not None
    assert branches.create_op.path == "/api/plugins/branching/branches/"
    assert branches.get_op is not None
    assert branches.get_op.path == "/api/plugins/branching/branches/{id}/"
    assert [a.path for a in branches.custom_actions] == [
        "/api/plugins/branching/branches/{id}/merge/"
    ]
    changes = resources["changes"]
    assert changes.list_op is not None
    assert changes.list_op.path == "/api/plugins/branching/changes/"
    assert changes.create_op is None


def test_plugin_with_its_own_tag_keeps_it() -> None:
    model = _build(
        {
            "/api/plugins/my-plugin/widgets/": {
                "get": _op("plugins_my_plugin_widgets_list", "my_plugin")
            }
        }
    )
    widgets = model.tags["my_plugin"].resources["widgets"]
    assert widgets.list_op is not None
    assert widgets.list_op.path == "/api/plugins/my-plugin/widgets/"


def test_two_plugins_under_the_generic_tag_stay_separate() -> None:
    model = _build(
        {
            "/api/plugins/branching/changes/": {
                "get": _op("plugins_branching_changes_list", "plugins")
            },
            "/api/plugins/netbox-dns/zones/": {
                "get": _op("plugins_netbox_dns_zones_list", "plugins")
            },
        }
    )
    assert set(model.tags["branching"].resources) == {"changes"}
    assert set(model.tags["netbox-dns"].resources) == {"zones"}


def test_plugin_root_view_is_skipped() -> None:
    model = _build({"/api/plugins/branching/": {"get": _op("plugins_branching_root", "plugins")}})
    assert model.tags == {}


def test_plugin_list_serializer_is_indexed_to_its_resource() -> None:
    list_op = _op("plugins_branching_branches_list", "plugins")
    list_op["responses"] = {
        "200": {
            "description": "OK",
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/PaginatedBranchList"}}
            },
        }
    }
    doc_dict: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {"title": "Test", "version": "0.0.1"},
        "paths": {"/api/plugins/branching/branches/": {"get": list_op}},
        "components": {
            "schemas": {
                "PaginatedBranchList": {
                    "type": "object",
                    "properties": {
                        "results": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Branch"},
                        }
                    },
                },
                "Branch": {"type": "object", "properties": {"id": {"type": "integer"}}},
            }
        },
    }
    body = json.dumps(doc_dict).encode()
    doc = OpenAPIDocument.model_validate(doc_dict)
    model = build_command_model(
        LoadedSchema(source="<test>", body=body, hash=canonical_sha256(body), document=doc)
    )
    assert model.fk_resources["Branch"] == FkResourceRef(tag="branching", resource="branches")
