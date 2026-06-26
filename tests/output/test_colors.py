from __future__ import annotations

from nsc.output.colors import ColoredValue, normalize_hex


def test_normalize_hex_strips_leading_hash_and_lowercases() -> None:
    assert normalize_hex("#4CAF50") == "4caf50"
    assert normalize_hex("4CAF50") == "4caf50"


def test_normalize_hex_rejects_non_hex_and_wrong_length() -> None:
    assert normalize_hex("ggg") is None
    assert normalize_hex("abc") is None
    assert normalize_hex("4caf5") is None
    assert normalize_hex("4caf500") is None
    assert normalize_hex(None) is None
    assert normalize_hex(123) is None


def test_normalize_hex_treats_empty_string_as_none() -> None:
    assert normalize_hex("") is None


def test_colored_value_is_frozen_dataclass() -> None:
    cv = ColoredValue("Router", "4caf50")
    assert cv.text == "Router"
    assert cv.color == "4caf50"
    assert ColoredValue("Router", "4caf50") == cv
