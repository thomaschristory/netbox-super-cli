from __future__ import annotations

from nsc.tui.columns import ColumnSelection, available_columns


def test_available_columns_is_ordered_union_of_top_level_keys() -> None:
    records = [
        {"id": 1, "name": "sw1", "site": {"id": 3, "url": "u", "display": "HQ"}},
        {"id": 2, "name": "sw2", "status": {"value": "active", "label": "Active"}},
    ]
    cols = available_columns(records)
    # first-seen order; FK/choice objects stay a single top-level column (the
    # table renders them via display/label) — no role.id / site.display noise.
    assert cols == ["id", "name", "site", "status"]
    assert "site.display" not in cols
    assert "site.url" not in cols


def test_available_columns_expands_custom_fields_into_dotted_subcolumns() -> None:
    records = [{"id": 1, "name": "sw1", "custom_fields": {"rack_role": "core", "floor": 3}}]
    cols = available_columns(records)
    assert cols == ["id", "name", "custom_fields.rack_role", "custom_fields.floor"]
    assert "custom_fields" not in cols


def test_custom_fields_keys_are_first_seen_union_across_records() -> None:
    records = [
        {"id": 1, "custom_fields": {"a": 1, "b": 2}},
        {"id": 2, "custom_fields": {"b": 2, "c": 3}},
    ]
    cols = available_columns(records)
    assert cols == ["id", "custom_fields.a", "custom_fields.b", "custom_fields.c"]


def test_custom_fields_object_and_null_values_still_listed() -> None:
    records = [{"custom_fields": {"site": {"id": 1, "display": "HQ"}, "note": None, "tag": "x"}}]
    cols = available_columns(records)
    assert cols == ["custom_fields.site", "custom_fields.note", "custom_fields.tag"]


def test_empty_or_missing_custom_fields_offers_no_cf_columns() -> None:
    assert available_columns([{"id": 1, "name": "sw1"}]) == ["id", "name"]
    assert available_columns([{"id": 1, "name": "sw1", "custom_fields": {}}]) == ["id", "name"]


def test_non_custom_fields_objects_are_not_expanded() -> None:
    records = [
        {
            "id": 1,
            "site": {"id": 3, "display": "HQ"},
            "status": {"value": "active", "label": "Active"},
            "custom_fields": {"x": 1},
        }
    ]
    cols = available_columns(records)
    assert cols == ["id", "site", "status", "custom_fields.x"]
    assert "site.display" not in cols
    assert "status.label" not in cols


def test_selection_round_trips_a_chosen_custom_field() -> None:
    records = [{"id": 1, "name": "sw1", "custom_fields": {"rack_role": "core"}}]
    sel = ColumnSelection(available=available_columns(records), visible=["name"])
    sel.toggle("custom_fields.rack_role")
    assert sel.visible_in_order() == ["name", "custom_fields.rack_role"]


def test_selection_orders_visible_first_then_the_rest() -> None:
    sel = ColumnSelection(available=["id", "name", "status", "site"], visible=["name", "id"])
    assert sel.items == ["name", "id", "status", "site"]
    assert sel.visible_in_order() == ["name", "id"]


def test_selection_keeps_visible_columns_absent_from_available() -> None:
    sel = ColumnSelection(available=["id", "name"], visible=["name", "custom_fields.x"])
    assert "custom_fields.x" in sel.items
    assert sel.visible_in_order() == ["name", "custom_fields.x"]


def test_toggle_changes_visibility_and_order_reflects_it() -> None:
    sel = ColumnSelection(available=["id", "name", "status"], visible=["id", "name"])
    sel.toggle("status")  # show
    assert sel.visible_in_order() == ["id", "name", "status"]
    sel.toggle("id")  # hide
    assert sel.visible_in_order() == ["name", "status"]
    assert not sel.is_visible("id")


def test_move_up_and_down_reorder_with_edge_no_ops() -> None:
    sel = ColumnSelection(available=["a", "b", "c"], visible=["a", "b", "c"])
    assert sel.move_up(0) == 0  # already at top: no-op
    assert sel.items == ["a", "b", "c"]
    assert sel.move_down(0) == 1
    assert sel.items == ["b", "a", "c"]
    assert sel.move_down(2) == 2  # already at bottom: no-op
    assert sel.items == ["b", "a", "c"]
    assert sel.move_up(2) == 1
    assert sel.items == ["b", "c", "a"]
    assert sel.visible_in_order() == ["b", "c", "a"]
