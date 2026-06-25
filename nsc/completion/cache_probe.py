"""Cheap on-disk reads for completion.

This module deliberately avoids importing `nsc.schema.source` (which pulls in
httpx and the schema-build pipeline). It reads the cached `CommandModel`
JSON directly via `CacheStore`, which validates the file but performs no
network I/O. Picking the newest cache file for a profile means we never need
the live schema hash at TAB time.
"""

from __future__ import annotations

from nsc.cache.store import CacheStore
from nsc.config.models import Config
from nsc.config.settings import Paths
from nsc.model.command_model import CommandModel

_PROFILE_FLAGS = frozenset({"--profile"})


def load_cached_model_for_profile(paths: Paths, profile: str) -> CommandModel | None:
    """Load the most-recently-fetched cached `CommandModel` for `profile`,
    or `None` if nothing usable is on disk. Never fetches over the network."""
    profile_dir = paths.cache_dir / profile
    if not profile_dir.exists():
        return None
    store = CacheStore(root=paths.cache_dir)
    try:
        candidates = sorted(
            (p for p in profile_dir.glob("*.json") if not p.name.endswith(".meta.json")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None
    for candidate in candidates:
        try:
            model = store.load(profile, candidate.stem)
        except Exception:
            continue
        if model is not None:
            return model
    return None


def resolve_completion_profile(
    config: Config, *, args: list[str], env: dict[str, str]
) -> str | None:
    """Resolve the profile name to complete against, mirroring runtime
    precedence: `--profile` flag > `NSC_PROFILE` env > config default_profile.

    Returns `None` when none of those are set; the caller then falls back to
    any single cache directory present on disk.
    """
    flag = _extract_profile_flag(args)
    if flag is not None:
        return flag
    env_profile = env.get("NSC_PROFILE")
    if env_profile:
        return env_profile
    return config.default_profile


def _extract_profile_flag(args: list[str]) -> str | None:
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--profile="):
            return arg.split("=", 1)[1]
        if arg in _PROFILE_FLAGS and i + 1 < len(args):
            return args[i + 1]
        i += 1
    return None
