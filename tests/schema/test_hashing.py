"""Tests for canonical schema hashing."""

from __future__ import annotations

import pytest

from nsc.schema.hashing import canonical_sha256


def test_same_content_different_key_order_hashes_identically() -> None:
    a = b'{"a": 1, "b": 2}'
    b = b'{"b": 2, "a": 1}'
    assert canonical_sha256(a) == canonical_sha256(b)


def test_different_content_hashes_differently() -> None:
    a = b'{"a": 1}'
    b = b'{"a": 2}'
    assert canonical_sha256(a) != canonical_sha256(b)


def test_returns_hex_string_of_expected_length() -> None:
    h = canonical_sha256(b"{}")
    assert isinstance(h, str)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_invalid_json_raises() -> None:
    with pytest.raises(ValueError):
        canonical_sha256(b"not json")
