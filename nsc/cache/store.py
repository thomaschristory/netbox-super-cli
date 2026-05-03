"""Persist generated CommandModels under `~/.nsc/cache/<profile>/<hash>.json`."""

from __future__ import annotations

import logging
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from nsc.config.models import Config, Profile
from nsc.model.command_model import CommandModel

_LOG = logging.getLogger(__name__)
_PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class CacheEntry:
    profile: str
    schema_hash: str
    path: Path


@dataclass(frozen=True, slots=True)
class PrunePlan:
    orphan_profile_dirs: list[Path]
    stale_hash_files: list[Path]
    aged_files: list[Path]

    def total_count(self) -> int:
        return len(self.orphan_profile_dirs) + len(self.stale_hash_files) + len(self.aged_files)

    def total_bytes(self) -> int:
        total = 0
        for d in self.orphan_profile_dirs:
            for f in d.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        for f in (*self.stale_hash_files, *self.aged_files):
            if f.exists():
                total += f.stat().st_size
        return total


@dataclass(frozen=True, slots=True)
class CacheStore:
    root: Path

    def load(self, profile: str, schema_hash: str) -> CommandModel | None:
        self._validate_profile(profile)
        if not _HASH_RE.match(schema_hash):
            return None
        target = self._path_for(profile, schema_hash)
        if not target.exists():
            return None
        try:
            text = target.read_text()
            model = CommandModel.model_validate_json(text)
        except Exception as exc:  # broad: corrupt JSON, schema mismatch, etc.
            _LOG.warning("cache: ignoring corrupt entry %s (%s)", target, exc)
            return None
        if model.schema_hash != schema_hash:
            _LOG.warning("cache: hash mismatch for %s (file says %s)", target, model.schema_hash)
            return None
        return model

    def save(self, profile: str, model: CommandModel) -> Path:
        self._validate_profile(profile)
        target = self._path_for(profile, model.schema_hash)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(model.model_dump_json(indent=2))
        return target

    def clear(self, *, profile: str | None = None) -> None:
        if profile is None:
            if self.root.exists():
                shutil.rmtree(self.root)
            return
        self._validate_profile(profile)
        target = self.root / profile
        if target.exists():
            shutil.rmtree(target)

    def move(self, old: str, new: str) -> None:
        """Rename a profile's cache directory from `old` to `new`.

        No-op when `old` does not exist (the profile was never warmed). Raises
        `FileExistsError` when `new` already exists — the caller must purge
        the target first if that's the intent. Both names are validated to
        prevent path-component injection (matches `_PROFILE_RE`).
        """
        self._validate_profile(old)
        self._validate_profile(new)
        src = self.root / old
        dst = self.root / new
        if not src.exists():
            return
        if dst.exists():
            raise FileExistsError(f"cache directory for profile {new!r} already exists at {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)

    def purge(self, profile: str) -> None:
        """Remove a profile's cache directory entirely. No-op if missing."""
        self._validate_profile(profile)
        target = self.root / profile
        if target.exists():
            shutil.rmtree(target)

    def enumerate_caches(self) -> list[CacheEntry]:
        """Walk the cache root and return one CacheEntry per valid <profile>/<hash>.json file.

        Silently skips:
          - Entries in `self.root` that aren't directories.
          - Directories whose names don't match `_PROFILE_RE`.
          - Files whose stems don't match `_HASH_RE` or whose suffix isn't `.json`.
        """
        if not self.root.exists():
            return []
        entries: list[CacheEntry] = []
        for profile_dir in self.root.iterdir():
            if not profile_dir.is_dir():
                continue
            if not _PROFILE_RE.match(profile_dir.name):
                continue
            for cache_file in profile_dir.iterdir():
                if cache_file.suffix != ".json":
                    continue
                stem = cache_file.stem
                if not _HASH_RE.match(stem):
                    continue
                entries.append(
                    CacheEntry(profile=profile_dir.name, schema_hash=stem, path=cache_file)
                )
        return entries

    def _path_for(self, profile: str, schema_hash: str) -> Path:
        return self.root / profile / f"{schema_hash}.json"

    @staticmethod
    def _validate_profile(profile: str) -> None:
        if not _PROFILE_RE.match(profile):
            raise ValueError(f"invalid profile name {profile!r}: must match {_PROFILE_RE.pattern}")


_ADHOC_PROFILE = "adhoc"  # runtime.py sentinel for env-var-only invocations; never prune.


def _find_orphan_dirs(entries: list[CacheEntry], profile_names: set[str]) -> list[Path]:
    """Type A: return one Path per profile directory not in config (adhoc excluded)."""
    orphan_dirs: list[Path] = []
    seen_dirs: set[Path] = set()
    for entry in entries:
        if entry.profile == _ADHOC_PROFILE or entry.profile in profile_names:
            continue
        d = entry.path.parent
        if d not in seen_dirs:
            seen_dirs.add(d)
            orphan_dirs.append(d)
    return orphan_dirs


def _find_stale_files(
    entries: list[CacheEntry],
    profile_names: set[str],
    config: Config,
    fetch_live_hash: Callable[[Profile], str],
) -> list[Path]:
    """Type B: return files whose hash doesn't match the live hash; skip on fetcher error."""
    stale_files: list[Path] = []
    for name in profile_names:
        try:
            live_hash = fetch_live_hash(config.profiles[name])
        except Exception:  # tolerated per-profile; caller skips unreachable instances
            continue
        for entry in entries:
            if entry.profile == name and entry.schema_hash != live_hash:
                stale_files.append(entry.path)
    return stale_files


def _find_aged_files(
    entries: list[CacheEntry],
    orphan_dirs: list[Path],
    cutoff: float,
) -> list[Path]:
    """Type C: return files older than `cutoff`, excluding those inside orphan dirs."""
    orphan_paths = set(orphan_dirs)
    aged: list[Path] = []
    for entry in entries:
        if entry.path.parent in orphan_paths:
            continue
        try:
            mtime = entry.path.stat().st_mtime
        except FileNotFoundError:
            continue
        if mtime < cutoff:
            aged.append(entry.path)
    return aged


def compute_prune_plan(
    *,
    config: Config,
    store: CacheStore,
    fetch_live_hash: Callable[[Profile], str] | None = None,
    max_age_days: int | None = None,
    now: float | None = None,
) -> PrunePlan:
    """Classify cache entries into the three prune categories.

    Type A (orphan_profile_dirs): a profile directory whose name is not in
    `config.profiles` (and is not the `adhoc` sentinel).

    Type B (stale_hash_files): for an *active* profile, files whose
    `<schema_hash>` does not match the live schema's current hash.
    Requires `fetch_live_hash`. If the fetcher raises for a given profile,
    type B is silently skipped for that profile only.

    Type C (aged_files): files whose mtime is older than `max_age_days`.
    Independent of A and B but deduplicated against A: a file inside an
    orphan profile dir is reported under A only (the rmtree handles it).
    """
    entries = store.enumerate_caches()
    profile_names = set(config.profiles.keys())

    orphan_dirs = _find_orphan_dirs(entries, profile_names)

    stale_files = (
        _find_stale_files(entries, profile_names, config, fetch_live_hash)
        if fetch_live_hash is not None
        else []
    )

    aged = (
        _find_aged_files(
            entries,
            orphan_dirs,
            (now if now is not None else time.time()) - max_age_days * 86400,
        )
        if max_age_days is not None
        else []
    )

    return PrunePlan(
        orphan_profile_dirs=orphan_dirs,
        stale_hash_files=stale_files,
        aged_files=aged,
    )
