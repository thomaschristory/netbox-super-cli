"""Tests for the on-disk command-model cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from nsc.cache.store import CacheStore
from nsc.model.command_model import CommandModel, Tag


def _model(hash_: str = "a" * 64) -> CommandModel:
    return CommandModel(
        info_title="NetBox",
        info_version="4.1.0",
        schema_hash=hash_,
        tags={"dcim": Tag(name="dcim")},
    )


def test_miss_then_write_then_hit(tmp_path: Path) -> None:
    store = CacheStore(root=tmp_path)
    h = "a" * 64
    assert store.load("default", h) is None
    store.save("default", _model(h))
    loaded = store.load("default", h)
    assert loaded is not None
    assert loaded.schema_hash == h


def test_miss_on_different_hash(tmp_path: Path) -> None:
    store = CacheStore(root=tmp_path)
    store.save("default", _model("a" * 64))
    assert store.load("default", "b" * 64) is None


def test_per_profile_isolation(tmp_path: Path) -> None:
    store = CacheStore(root=tmp_path)
    store.save("prod", _model("a" * 64))
    assert store.load("lab", "a" * 64) is None
    assert store.load("prod", "a" * 64) is not None


def test_clear_removes_profile_cache(tmp_path: Path) -> None:
    store = CacheStore(root=tmp_path)
    store.save("prod", _model())
    store.clear(profile="prod")
    assert store.load("prod", "a" * 64) is None


def test_corrupt_cache_returns_none(tmp_path: Path) -> None:
    store = CacheStore(root=tmp_path)
    store.save("prod", _model("a" * 64))
    target = tmp_path / "prod" / ("a" * 64 + ".json")
    target.write_text("not json")
    assert store.load("prod", "a" * 64) is None


def test_load_rejects_hash_mismatch(tmp_path: Path) -> None:
    store = CacheStore(root=tmp_path)
    store.save("prod", _model("a" * 64))
    # Tamper the file content so its embedded hash differs from the filename
    target = tmp_path / "prod" / ("a" * 64 + ".json")
    target.write_text(_model("c" * 64).model_dump_json())
    assert store.load("prod", "a" * 64) is None


def test_invalid_profile_name_rejected(tmp_path: Path) -> None:
    store = CacheStore(root=tmp_path)
    with pytest.raises(ValueError):
        store.save("../escape", _model())
