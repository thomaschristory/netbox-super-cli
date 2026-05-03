"""Resolver unit tests for Phase 4c.

Builds small `CommandModel` fixtures locally rather than using a live schema
so the failure modes (unknown / ambiguous / verb-required-op-missing) are
unambiguous.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nsc.aliases import (
    AliasVerb,
    AmbiguousAlias,
    ResolvedAlias,
    UnknownAlias,
    resolve,
)
from nsc.model.command_model import (
    CommandModel,
    HttpMethod,
    Operation,
    Resource,
    Tag,
)


def _list_op(op_id: str, path: str) -> Operation:
    return Operation(operation_id=op_id, http_method=HttpMethod.GET, path=path)


def _get_op(op_id: str, path: str) -> Operation:
    return Operation(operation_id=op_id, http_method=HttpMethod.GET, path=path)


def _delete_op(op_id: str, path: str) -> Operation:
    return Operation(operation_id=op_id, http_method=HttpMethod.DELETE, path=path)


def _model(*tags: Tag) -> CommandModel:
    return CommandModel(
        info_title="t",
        info_version="v",
        schema_hash="h" * 64,
        tags={t.name: t for t in tags},
    )


def _devices_resource() -> Resource:
    return Resource(
        name="devices",
        list_op=_list_op("dcim_devices_list", "/api/dcim/devices/"),
        get_op=_get_op("dcim_devices_retrieve", "/api/dcim/devices/{id}/"),
        delete_op=_delete_op("dcim_devices_destroy", "/api/dcim/devices/{id}/"),
    )


def _read_only_resource(name: str, tag: str) -> Resource:
    """A resource with only a list_op — used to exercise verb-required gating."""
    return Resource(
        name=name,
        list_op=_list_op(f"{tag}_{name}_list", f"/api/{tag}/{name}/"),
    )


def test_resolve_ls_finds_unique_plural_resource() -> None:
    model = _model(Tag(name="dcim", resources={"devices": _devices_resource()}))
    result = resolve(AliasVerb.LS, "devices", model)
    assert isinstance(result, ResolvedAlias)
    assert result.tag == "dcim"
    assert result.resource_name == "devices"
    assert result.operation.operation_id == "dcim_devices_list"


def test_resolve_ls_is_case_insensitive() -> None:
    model = _model(Tag(name="dcim", resources={"devices": _devices_resource()}))
    assert isinstance(resolve(AliasVerb.LS, "DEVICES", model), ResolvedAlias)
    assert isinstance(resolve(AliasVerb.LS, "Devices", model), ResolvedAlias)


def test_resolve_ls_does_not_pluralize_singular_input() -> None:
    """Spec §11: plural-only is the v1 stance. `device` must NOT match `devices`."""
    model = _model(Tag(name="dcim", resources={"devices": _devices_resource()}))
    result = resolve(AliasVerb.LS, "device", model)
    assert isinstance(result, UnknownAlias)
    assert result.term == "device"


def test_resolve_ls_unknown_when_no_resource_named_term() -> None:
    model = _model(Tag(name="dcim", resources={"devices": _devices_resource()}))
    result = resolve(AliasVerb.LS, "racks", model)
    assert isinstance(result, UnknownAlias)
    assert result.term == "racks"


def test_resolve_ls_ambiguous_across_two_tags() -> None:
    model = _model(
        Tag(name="plugin_a", resources={"widgets": _read_only_resource("widgets", "plugin_a")}),
        Tag(name="plugin_b", resources={"widgets": _read_only_resource("widgets", "plugin_b")}),
    )
    result = resolve(AliasVerb.LS, "widgets", model)
    assert isinstance(result, AmbiguousAlias)
    # Candidates returned in deterministic (sorted-by-tag) order.
    assert result.candidates == [("plugin_a", "widgets"), ("plugin_b", "widgets")]


def test_resolve_rm_skips_resources_without_delete_op() -> None:
    """A resource that has list_op but no delete_op cannot match `rm`.

    This means verb-required-op gating happens BEFORE ambiguity classification:
    a tag whose resource lacks the required op is invisible to that verb.
    """
    devices_full = _devices_resource()
    devices_readonly = _read_only_resource("devices", "tenancy")
    model = _model(
        Tag(name="dcim", resources={"devices": devices_full}),
        Tag(name="tenancy", resources={"devices": devices_readonly}),
    )
    # ls sees both → ambiguous.
    ls_result = resolve(AliasVerb.LS, "devices", model)
    assert isinstance(ls_result, AmbiguousAlias)
    assert ls_result.candidates == [("dcim", "devices"), ("tenancy", "devices")]
    # rm sees only dcim (which has delete_op) → resolved.
    rm_result = resolve(AliasVerb.RM, "devices", model)
    assert isinstance(rm_result, ResolvedAlias)
    assert rm_result.tag == "dcim"
    assert rm_result.operation.http_method is HttpMethod.DELETE


def test_resolve_get_uses_get_op_when_present() -> None:
    model = _model(Tag(name="dcim", resources={"devices": _devices_resource()}))
    result = resolve(AliasVerb.GET, "devices", model)
    assert isinstance(result, ResolvedAlias)
    assert result.operation.operation_id == "dcim_devices_retrieve"


def test_resolve_get_unknown_when_resource_has_no_get_op() -> None:
    """A resource without get_op is not a `get` candidate even if list_op exists.

    Caller is expected to fall back to list+filter for the name-dereference
    path (Task 6) — but the resolver itself only reports the get_op match.
    """
    no_get = Resource(
        name="things",
        list_op=_list_op("dcim_things_list", "/api/dcim/things/"),
    )
    model = _model(Tag(name="dcim", resources={"things": no_get}))
    result = resolve(AliasVerb.GET, "things", model)
    assert isinstance(result, UnknownAlias)


def test_resolve_returns_frozen_models() -> None:
    """Belt-and-braces: callers must not mutate resolver output."""
    model = _model(Tag(name="dcim", resources={"devices": _devices_resource()}))
    result = resolve(AliasVerb.LS, "devices", model)
    assert isinstance(result, ResolvedAlias)
    with pytest.raises(ValidationError):
        result.tag = "other"
