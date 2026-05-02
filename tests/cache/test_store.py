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


def test_move_renames_profile_directory(tmp_path: Path) -> None:
    store = CacheStore(root=tmp_path)
    store.save("old-name", _model("a" * 64))
    store.move("old-name", "new-name")
    assert store.load("old-name", "a" * 64) is None
    assert store.load("new-name", "a" * 64) is not None


def test_move_is_a_noop_when_old_is_missing(tmp_path: Path) -> None:
    """`profiles rename` should not fail just because the profile was never used."""
    store = CacheStore(root=tmp_path)
    store.move("never-used", "renamed")  # must not raise


def test_move_refuses_to_overwrite_existing_target(tmp_path: Path) -> None:
    store = CacheStore(root=tmp_path)
    store.save("a", _model("a" * 64))
    store.save("b", _model("b" * 64))
    with pytest.raises(FileExistsError):
        store.move("a", "b")
    # Both still readable after the failed move.
    assert store.load("a", "a" * 64) is not None
    assert store.load("b", "b" * 64) is not None


def test_move_validates_both_names(tmp_path: Path) -> None:
    store = CacheStore(root=tmp_path)
    store.save("good-name", _model())
    with pytest.raises(ValueError):
        store.move("good-name", "../escape")
    with pytest.raises(ValueError):
        store.move("../escape", "good-name")


def test_purge_removes_profile_directory(tmp_path: Path) -> None:
    store = CacheStore(root=tmp_path)
    store.save("doomed", _model())
    store.purge("doomed")
    assert store.load("doomed", "a" * 64) is None
    assert not (tmp_path / "doomed").exists()


def test_purge_is_a_noop_when_profile_is_missing(tmp_path: Path) -> None:
    """Removing a profile that never had a cache must not raise."""
    store = CacheStore(root=tmp_path)
    store.purge("never-used")
