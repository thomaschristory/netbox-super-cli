"""Framework-free candidate generators for shell completion.

Pure functions: a `CommandModel` (or `None`) plus an `incomplete` prefix in,
a sorted, prefix-filtered list of candidate strings out. No Typer, no Click,
no I/O. The thin Click/Typer adapters live in `nsc.completion.callbacks`.
"""

from __future__ import annotations

from pathlib import Path

from nsc.config.loader import ConfigParseError, load_config
from nsc.config.settings import Paths
from nsc.model.command_model import CommandModel, Resource


def _verb_has_op(resource: Resource, verb: str) -> bool:
    if verb == "ls":
        return resource.list_op is not None
    if verb == "get":
        return resource.get_op is not None
    if verb == "rm":
        return resource.delete_op is not None
    # `search` is not resource-name driven; treat anything else as list-capable.
    return resource.list_op is not None


def resource_name_candidates(
    model: CommandModel | None, *, verb: str, incomplete: str
) -> list[str]:
    """Resource names (e.g. `devices`, `device-roles`) that support `verb`,
    filtered by the `incomplete` prefix. Sorted and de-duplicated across tags."""
    if model is None:
        return []
    needle = incomplete.lower()
    matches: set[str] = set()
    for tag in model.tags.values():
        for name, resource in tag.resources.items():
            if not name.lower().startswith(needle):
                continue
            if _verb_has_op(resource, verb):
                matches.add(name)
    return sorted(matches)


def profile_candidates(paths: Paths, *, incomplete: str) -> list[str]:
    """Profile names from `~/.nsc/config.yaml`, filtered by prefix. Returns
    `[]` for a missing or unparseable config — completion must not crash."""
    try:
        config = load_config(paths.config_file)
    except (ConfigParseError, OSError):
        return []
    needle = incomplete.lower()
    return sorted(name for name in config.profiles if name.lower().startswith(needle))


def cache_dir_profile_names(paths: Paths) -> list[str]:
    """Profile subdirectory names present under the cache dir. Used as a last
    resort when no config/flag/env pins a profile."""
    cache_dir: Path = paths.cache_dir
    if not cache_dir.exists():
        return []
    try:
        return sorted(p.name for p in cache_dir.iterdir() if p.is_dir())
    except OSError:
        return []
