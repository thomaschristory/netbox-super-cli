"""On-disk locations for `~/.nsc/`."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Paths:
    root: Path

    @property
    def config_file(self) -> Path:
        return self.root / "config.yaml"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"


def default_paths() -> Paths:
    """Return the default `~/.nsc/` Paths, honoring `NSC_HOME` if set."""
    override = os.environ.get("NSC_HOME")
    if override:
        return Paths(root=Path(override).expanduser().resolve())
    return Paths(root=Path.home() / ".nsc")
