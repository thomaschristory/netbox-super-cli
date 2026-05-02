"""Dotted-path mutators on the round-trip CommentedMap."""

from __future__ import annotations

from pathlib import Path

import pytest

from nsc.config.writer import (
    ConfigWriteError,
    dump_round_trip,
    load_round_trip,
    set_path,
    unset_path,
)


def _make_doc(tmp_path: Path, body: str = "") -> object:
    p = tmp_path / "config.yaml"
    p.write_text(body, encoding="utf-8")
    return load_round_trip(p)


def test_set_path_creates_intermediate_maps(tmp_path: Path) -> None:
    doc = _make_doc(tmp_path)
    set_path(doc, "defaults.page_size", 100)
    out = dump_round_trip(doc)
    assert "defaults:" in out
    assert "page_size: 100" in out


def test_set_path_overwrites_scalar(tmp_path: Path) -> None:
    doc = _make_doc(tmp_path, "defaults:\n  page_size: 50\n")
    set_path(doc, "defaults.page_size", 100)
    out = dump_round_trip(doc)
    assert "page_size: 100" in out
    assert "page_size: 50" not in out


def test_set_path_refuses_to_overwrite_map_with_scalar(tmp_path: Path) -> None:
    doc = _make_doc(tmp_path, "profiles:\n  prod:\n    url: https://x/\n")
    with pytest.raises(ConfigWriteError, match="map"):
        set_path(doc, "profiles", "scalar-value")


def test_set_path_refuses_to_overwrite_scalar_with_map(tmp_path: Path) -> None:
    doc = _make_doc(tmp_path, "default_profile: prod\n")
    with pytest.raises(ConfigWriteError, match="scalar"):
        set_path(doc, "default_profile.something", "x")


def test_unset_path_removes_leaf(tmp_path: Path) -> None:
    doc = _make_doc(tmp_path, "defaults:\n  page_size: 50\n  output: table\n")
    unset_path(doc, "defaults.page_size")
    out = dump_round_trip(doc)
    assert "page_size" not in out
    assert "output: table" in out


def test_unset_path_prunes_empty_parents(tmp_path: Path) -> None:
    doc = _make_doc(tmp_path, "defaults:\n  page_size: 50\n")
    unset_path(doc, "defaults.page_size")
    out = dump_round_trip(doc)
    assert "defaults" not in out


def test_unset_path_no_op_on_missing_leaf(tmp_path: Path) -> None:
    doc = _make_doc(tmp_path, "defaults:\n  page_size: 50\n")
    unset_path(doc, "defaults.timeout")
    out = dump_round_trip(doc)
    assert "page_size: 50" in out


def test_unset_path_no_op_on_missing_intermediate(tmp_path: Path) -> None:
    doc = _make_doc(tmp_path, "default_profile: prod\n")
    unset_path(doc, "defaults.page_size")
    out = dump_round_trip(doc)
    assert "default_profile: prod" in out
