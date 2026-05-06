"""Access to the bundled portable Skill file.

The canonical source of truth lives at `skills/netbox-super-cli/SKILL.md` at
the repo root; `pyproject.toml`'s wheel `force-include` ships the same path
inside the installed wheel. The helper below uses `importlib.resources` so
both layouts work without special-casing.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import as_file, files
from pathlib import Path

__all__ = ["BUNDLE_NAME", "bundle_path"]

BUNDLE_NAME = "netbox-super-cli"
"""The bundled Skill's directory name; used by the install helper to derive
the per-target destination directory."""


@contextmanager
def bundle_path() -> Iterator[Path]:
    """Yield an on-disk Path to the bundled `SKILL.md`.

    Works in both the source-tree layout (file lives at
    `<repo>/skills/netbox-super-cli/SKILL.md`) and the installed-wheel layout
    (same relative path inside the wheel; `importlib.resources.as_file` will
    materialize a real file when reading from a zipped wheel).
    """
    nsc_root = files("nsc")
    skill_md = nsc_root.joinpath("..", "skills", BUNDLE_NAME, "SKILL.md")
    with as_file(skill_md) as p:
        yield p
