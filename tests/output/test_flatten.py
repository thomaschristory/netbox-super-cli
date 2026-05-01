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
