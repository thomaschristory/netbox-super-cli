from __future__ import annotations

from nsc.output.flatten import flatten


def test_flatten_passes_scalars_through() -> None:
    assert flatten({"id": 1, "name": "x"}) == {"id": 1, "name": "x"}


def test_flatten_descends_one_level() -> None:
    assert flatten({"site": {"id": 7, "name": "DC1"}}) == {"site.id": 7, "site.name": "DC1"}


def test_flatten_descends_multiple_levels() -> None:
    assert flatten({"a": {"b": {"c": 1}}}) == {"a.b.c": 1}


def test_flatten_serializes_lists_as_json() -> None:
    out = flatten({"tags": ["red", "blue"]})
    assert out["tags"] == '["red", "blue"]' or out["tags"] == '["red","blue"]'


def test_flatten_handles_none_values() -> None:
    assert flatten({"name": None}) == {"name": None}


def test_flatten_pick_returns_only_requested_keys() -> None:
    out = flatten({"id": 1, "name": "x", "extra": 9}, columns=["id", "name"])
    assert out == {"id": 1, "name": "x"}


def test_flatten_pick_returns_blank_for_missing_keys() -> None:
    out = flatten({"id": 1}, columns=["id", "name"])
    assert out == {"id": 1, "name": ""}


def test_flatten_pick_renders_nested_object_via_display() -> None:
    record = {"role": {"id": 1, "name": "Router", "display": "Router"}}
    assert flatten(record, columns=["role"]) == {"role": "Router"}


def test_flatten_pick_nested_object_without_display_falls_back_to_json() -> None:
    assert flatten({"obj": {"a": 1}}, columns=["obj"]) == {"obj": '{"a":1}'}


def test_flatten_pick_choice_field_renders_label() -> None:
    record = {"status": {"value": "active", "label": "Active"}}
    assert flatten(record, columns=["status"]) == {"status": "Active"}


def test_flatten_pick_display_takes_precedence_over_label() -> None:
    record = {"x": {"display": "Disp", "label": "Lab"}}
    assert flatten(record, columns=["x"]) == {"x": "Disp"}


def test_flatten_pick_choice_field_value_still_available_via_dotted_path() -> None:
    record = {"status": {"value": "active", "label": "Active"}}
    assert flatten(record, columns=["status.value"]) == {"status.value": "active"}


def test_flatten_pick_joins_list_of_choice_fields_via_label() -> None:
    record = {"vals": [{"label": "A"}, {"label": "B"}]}
    assert flatten(record, columns=["vals"]) == {"vals": "A, B"}


def test_flatten_pick_non_string_label_falls_back_to_json() -> None:
    assert flatten({"x": {"label": 7}}, columns=["x"]) == {"x": '{"label":7}'}


def test_flatten_pick_joins_mixed_display_and_label_list() -> None:
    record = {"items": [{"display": "D1"}, {"label": "L1"}]}
    assert flatten(record, columns=["items"]) == {"items": "D1, L1"}


def test_flatten_pick_resolves_dotted_path_into_nested_object() -> None:
    assert flatten({"role": {"name": "Router"}}, columns=["role.name"]) == {"role.name": "Router"}


def test_flatten_pick_joins_list_of_objects_via_display() -> None:
    record = {"tags": [{"display": "prod"}, {"display": "edge"}]}
    assert flatten(record, columns=["tags"]) == {"tags": "prod, edge"}


def test_flatten_pick_joins_list_of_scalars() -> None:
    assert flatten({"tags": ["red", "blue"]}, columns=["tags"]) == {"tags": "red, blue"}


def test_flatten_pick_empty_list_renders_blank() -> None:
    assert flatten({"tags": []}, columns=["tags"]) == {"tags": ""}


def test_flatten_pick_null_foreign_key_renders_none() -> None:
    assert flatten({"platform": None}, columns=["platform"]) == {"platform": None}


def test_flatten_pick_dotted_path_through_null_renders_blank() -> None:
    assert flatten({"site": None}, columns=["site.name"]) == {"site.name": ""}


def test_flatten_pick_dotted_path_landing_on_list_joins() -> None:
    record = {"config": {"tags": ["a", "b"]}}
    assert flatten(record, columns=["config.tags"]) == {"config.tags": "a, b"}


def test_flatten_pick_list_of_objects_without_display_uses_json() -> None:
    record = {"items": [{"a": 1}, {"b": 2}]}
    assert flatten(record, columns=["items"]) == {"items": '{"a":1}, {"b":2}'}


def test_flatten_pick_list_with_none_renders_empty_token() -> None:
    assert flatten({"vals": ["x", None, "y"]}, columns=["vals"]) == {"vals": "x, , y"}


def test_flatten_pick_dotted_path_is_traversal_not_literal_key() -> None:
    # The dotted column resolves by traversing nested dicts, matching the
    # documented "drills in" semantics — it does not match a literal dotted key.
    assert flatten({"a": {"b": 5}}, columns=["a.b"]) == {"a.b": 5}
