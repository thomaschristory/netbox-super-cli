"""Tests for cache prune helpers (Phase 5a)."""

from __future__ import annotations

from pathlib import Path

from nsc.cache.store import CacheEntry, CacheStore


def _seed(root: Path, profile: str, schema_hash: str) -> Path:
    """Write an empty cache file at root/profile/<hash>.json and return the path."""
    profile_dir = root / profile
    profile_dir.mkdir(parents=True, exist_ok=True)
    target = profile_dir / f"{schema_hash}.json"
    target.write_text("{}")
    return target


def test_enumerate_caches_empty_root_returns_no_entries(tmp_path: Path) -> None:
    store = CacheStore(root=tmp_path)
    assert list(store.enumerate_caches()) == []


def test_enumerate_caches_returns_one_entry_per_hash_file(tmp_path: Path) -> None:
    store = CacheStore(root=tmp_path)
    p1 = _seed(tmp_path, "prod", "a" * 64)
    p2 = _seed(tmp_path, "prod", "b" * 64)
    p3 = _seed(tmp_path, "lab", "c" * 64)
    entries = sorted(store.enumerate_caches(), key=lambda e: (e.profile, e.schema_hash))
    assert entries == [
        CacheEntry(profile="lab", schema_hash="c" * 64, path=p3),
        CacheEntry(profile="prod", schema_hash="a" * 64, path=p1),
        CacheEntry(profile="prod", schema_hash="b" * 64, path=p2),
    ]


def test_enumerate_caches_skips_non_hash_filenames(tmp_path: Path) -> None:
    store = CacheStore(root=tmp_path)
    _seed(tmp_path, "prod", "a" * 64)
    (tmp_path / "prod" / "README.md").write_text("note")
    (tmp_path / "prod" / "garbage.json").write_text("{}")
    entries = list(store.enumerate_caches())
    assert len(entries) == 1
    assert entries[0].schema_hash == "a" * 64


def test_enumerate_caches_skips_invalid_profile_dirs(tmp_path: Path) -> None:
    """Directories whose names don't match _PROFILE_RE are ignored, not raised."""
    store = CacheStore(root=tmp_path)
    _seed(tmp_path, "prod", "a" * 64)
    (tmp_path / ".DS_Store").touch()
    (tmp_path / "weird name").mkdir()
    entries = list(store.enumerate_caches())
    assert len(entries) == 1
    assert entries[0].profile == "prod"
