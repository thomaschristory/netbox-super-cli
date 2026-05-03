"""Tests for cache prune helpers (Phase 5a)."""

from __future__ import annotations

import os
import time
from pathlib import Path

from nsc.cache.store import CacheEntry, CacheStore, compute_prune_plan
from nsc.config.models import Config, Profile


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


# ---------------------------------------------------------------------------
# Task 2: PrunePlan + compute_prune_plan
# ---------------------------------------------------------------------------


def _config(profile_names: list[str]) -> Config:
    profiles = {
        name: Profile(name=name, url="https://example.com", token="xxx") for name in profile_names
    }
    return Config(profiles=profiles, default_profile=profile_names[0] if profile_names else None)


def test_compute_prune_plan_type_a_orphan_profile_dir(tmp_path: Path) -> None:
    """Profile dirs not in config are orphan_profile_dirs; the dir itself is the unit, not files."""
    store = CacheStore(root=tmp_path)
    _seed(tmp_path, "prod", "a" * 64)
    _seed(tmp_path, "removed", "b" * 64)
    config = _config(["prod"])

    plan = compute_prune_plan(config=config, store=store)

    assert plan.orphan_profile_dirs == [tmp_path / "removed"]
    assert plan.stale_hash_files == []
    assert plan.aged_files == []


def test_compute_prune_plan_never_prunes_adhoc(tmp_path: Path) -> None:
    """The 'adhoc' sentinel from runtime.py covers env-var-only invocations; preserve it."""
    store = CacheStore(root=tmp_path)
    _seed(tmp_path, "adhoc", "a" * 64)
    config = _config(["prod"])  # 'adhoc' is not in config

    plan = compute_prune_plan(config=config, store=store)

    assert plan.orphan_profile_dirs == []


def test_compute_prune_plan_type_b_stale_hash(tmp_path: Path) -> None:
    """For active profiles, files whose hash != live_hash are stale_hash_files."""
    store = CacheStore(root=tmp_path)
    p_old = _seed(tmp_path, "prod", "a" * 64)
    p_new = _seed(tmp_path, "prod", "b" * 64)
    config = _config(["prod"])

    def fetcher(profile: Profile) -> str:
        return "b" * 64  # live = b; the 'a' file is stale

    plan = compute_prune_plan(config=config, store=store, fetch_live_hash=fetcher)

    assert plan.stale_hash_files == [p_old]
    assert p_new not in plan.stale_hash_files


def test_compute_prune_plan_skips_type_b_when_fetcher_raises(tmp_path: Path) -> None:
    """Per-profile fetcher failure should skip type B for that profile, not abort overall."""
    store = CacheStore(root=tmp_path)
    _seed(tmp_path, "prod", "a" * 64)
    _seed(tmp_path, "lab", "c" * 64)

    # 'lab' profile has an offline URL so the fetcher will raise for it.
    prod_profile = Profile(name="prod", url="https://example.com", token="xxx")
    lab_profile = Profile(name="lab", url="https://offline.example.com", token="xxx")
    config = Config(
        profiles={"prod": prod_profile, "lab": lab_profile},
        default_profile="prod",
    )

    def fetcher(profile: Profile) -> str:
        if str(profile.url).startswith("https://offline"):
            raise RuntimeError("offline")
        return "z" * 64  # everything's stale on the reachable side

    plan = compute_prune_plan(config=config, store=store, fetch_live_hash=fetcher)

    # 'prod' is reachable -> its 'a' file is stale.
    # 'lab' is offline -> skipped, no entries.
    assert plan.stale_hash_files == [tmp_path / "prod" / ("a" * 64 + ".json")]


def test_compute_prune_plan_type_c_age_based(tmp_path: Path) -> None:
    """--max-age <days>: any cache file with mtime older than the cutoff is aged_files."""
    store = CacheStore(root=tmp_path)
    new_path = _seed(tmp_path, "prod", "a" * 64)
    old_path = _seed(tmp_path, "prod", "b" * 64)
    # Backdate the 'b' file by 100 days.
    old_mtime = time.time() - 100 * 86400
    os.utime(old_path, (old_mtime, old_mtime))
    config = _config(["prod"])

    plan = compute_prune_plan(config=config, store=store, max_age_days=30)

    assert plan.aged_files == [old_path]
    assert new_path not in plan.aged_files


def test_compute_prune_plan_dedupes_overlap(tmp_path: Path) -> None:
    """An old file in an orphan profile shows up only in orphan_profile_dirs (the dir wins)."""
    store = CacheStore(root=tmp_path)
    p = _seed(tmp_path, "removed", "a" * 64)
    # Backdate to trigger type C as well.
    old_mtime = time.time() - 100 * 86400
    os.utime(p, (old_mtime, old_mtime))
    config = _config(["prod"])

    plan = compute_prune_plan(config=config, store=store, max_age_days=30)

    assert plan.orphan_profile_dirs == [tmp_path / "removed"]
    # The file is NOT also listed under aged_files: the directory rmtree handles it.
    assert plan.aged_files == []
