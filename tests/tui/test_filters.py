from __future__ import annotations

from nsc.model.command_model import Operation, Parameter, ParameterLocation
from nsc.tui.filters import (
    FilterState,
    common_filters,
    parse_raw,
    searchable_filters,
)


def _q(name: str, enum: list[str] | None = None) -> Parameter:
    return Parameter(name=name, location=ParameterLocation.QUERY, enum=enum)


def _op() -> Operation:
    params = [
        _q("q"),
        _q("status", enum=["active", "offline"]),
        _q("name"),
        _q("name__ic"),
        _q("site"),
        _q("site_id"),
        _q("interface_count"),
        _q("created_by_request"),
        _q("limit"),
        _q("offset"),
        _q("ordering"),
        _q("zzz_obscure"),
    ]
    return Operation(operation_id="x_list", http_method="GET", path="/api/x/", parameters=params)


def test_common_filters_picks_q_enums_and_allowlist_drops_junk() -> None:
    names = [p.name for p in common_filters(_op())]
    assert names[0] == "q"  # q first, labelled search in the UI
    assert "status" in names  # enum
    assert "name" in names and "site" in names  # allowlist
    # dropped junk and lookups never appear in the common form
    for absent in (
        "name__ic",
        "interface_count",
        "created_by_request",
        "limit",
        "offset",
        "ordering",
        "zzz_obscure",
    ):
        assert absent not in names
    # x/x_id dedup: the allowlist base name wins, _id is not added
    assert "site_id" not in names


def test_searchable_includes_lookups_excludes_only_control_junk() -> None:
    names = {p.name for p in searchable_filters(_op())}
    assert "name__ic" in names  # lookups reachable via search
    assert "site_id" in names
    assert "zzz_obscure" in names
    for absent in ("limit", "offset", "ordering", "interface_count", "created_by_request"):
        assert absent not in names


def test_parse_raw_splits_pairs_and_ignores_malformed() -> None:
    assert parse_raw("status=active site=hq") == {"status": "active", "site": "hq"}
    assert parse_raw("  bad  name=sw1 ") == {"name": "sw1"}
    assert parse_raw("") == {}


def test_filter_state_roundtrips_set_remove_and_params() -> None:
    state = FilterState.from_params({"status": "active"})
    state.set("site", "hq")
    state.set("status", "offline")  # overwrite
    assert state.as_params() == {"status": "offline", "site": "hq"}
    state.remove("status")
    assert state.as_params() == {"site": "hq"}
    state.set("name", "")  # empty value clears
    assert "name" not in state.as_params()
