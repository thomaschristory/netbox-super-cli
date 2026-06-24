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


def test_common_filters_surfaces_status_when_enum_is_none() -> None:
    # NetBox flattens the multi-value `status` array param to enum=None, so the
    # enum auto-include rule misses it; the allowlist must carry it like `role`.
    op = Operation(
        operation_id="dev_list",
        http_method="GET",
        path="/api/dcim/devices/",
        parameters=[
            _q("q"),
            _q("status", enum=None),
            _q("name"),
        ],
    )
    names = [p.name for p in common_filters(op)]
    assert "status" in names


def test_common_filters_dedups_x_id_when_base_present() -> None:
    # When both an allowlist base name and its `_id` form exist, only the base
    # name is curated; the `_id` form stays reachable via search.
    op = Operation(
        operation_id="x_list",
        http_method="GET",
        path="/api/x/",
        parameters=[_q("site"), _q("site_id", enum=["1", "2"])],
    )
    names = [p.name for p in common_filters(op)]
    assert "site" in names
    assert "site_id" not in names


def test_common_filters_caps_at_twenty() -> None:
    params = [_q(f"enum{i}", enum=["a", "b"]) for i in range(30)]
    op = Operation(operation_id="x_list", http_method="GET", path="/api/x/", parameters=params)
    assert len(common_filters(op)) == 20


def test_searchable_excludes_each_drop_exact_name() -> None:
    params = [_q(n) for n in ("start", "brief", "fields", "omit", "name")]
    op = Operation(operation_id="x_list", http_method="GET", path="/api/x/", parameters=params)
    names = {p.name for p in searchable_filters(op)}
    for absent in ("start", "brief", "fields", "omit"):
        assert absent not in names
    assert "name" in names


def test_parse_raw_splits_pairs_and_ignores_malformed() -> None:
    assert parse_raw("status=active site=hq") == {"status": "active", "site": "hq"}
    assert parse_raw("  bad  name=sw1 ") == {"name": "sw1"}
    assert parse_raw("") == {}


def test_parse_raw_edge_cases() -> None:
    assert parse_raw("expr=a=b") == {"expr": "a=b"}  # value may contain '='
    assert parse_raw("name=") == {}  # empty value is a no-op, not a clear
    assert parse_raw("=val") == {}  # empty key dropped


def test_filter_state_roundtrips_set_remove_and_params() -> None:
    state = FilterState.from_params({"status": "active"})
    state.set("site", "hq")
    state.set("status", "offline")  # overwrite
    assert state.as_params() == {"status": "offline", "site": "hq"}
    state.remove("status")
    assert state.as_params() == {"site": "hq"}
    state.set("name", "")  # empty value clears
    assert "name" not in state.as_params()


def test_filter_state_from_params_drops_empty_values() -> None:
    assert FilterState.from_params({"a": "", "b": "2"}).as_params() == {"b": "2"}


def test_filter_state_merge_overwrites_adds_and_drops_empty() -> None:
    state = FilterState.from_params({"a": "1", "b": "2"})
    state.merge({"a": "9", "c": "3", "d": ""})
    assert state.as_params() == {"a": "9", "b": "2", "c": "3"}
