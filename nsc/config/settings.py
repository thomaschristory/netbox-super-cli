"""On-disk locations for `~/.nsc/`."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

# The nsc state tree (`~/.nsc` and everything under it) holds config tokens,
# audit bodies, and cached schemas; keep every directory we create owner-only,
# mirroring the 0600 file treatment in writer.py / audit.py.
_DIR_MODE = 0o700


def ensure_private_dir(directory: Path) -> None:
    """Create `directory` (with parents) and clamp the created chain to 0700.

    Every directory this call brings into existence — including an intermediate
    `~/.nsc` root that would otherwise inherit umask (~0755) — is set owner-only.
    A pre-existing leaf that is group/world-accessible is tightened too, so a
    `~/.nsc/logs` left 0755 by an older nsc version is fixed in place; but an
    already-restrictive leaf is left alone so a deliberately read-only dir still
    surfaces a write failure rather than being silently reopened. Pre-existing
    ancestors (e.g. `$HOME`) are never touched.
    """
    missing: list[Path] = []
    cursor = directory
    while not cursor.exists():
        missing.append(cursor)
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent
    directory.mkdir(parents=True, exist_ok=True)
    for created in missing:
        os.chmod(created, _DIR_MODE)
    if directory not in missing and stat.S_IMODE(directory.stat().st_mode) & 0o077:
        os.chmod(directory, _DIR_MODE)


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
