"""`ensure_private_dir` hardens the nsc state-root chain to 0700 (issue #90).

The `~/.nsc` root must be owner-only, not just its leaf dirs/files: it can
hold cache, logs, and config side by side, so a world/group-readable root
leaks directory listings on shared hosts.
"""

from __future__ import annotations

import stat
from pathlib import Path

from nsc.config.settings import ensure_private_dir


def test_creates_leaf_and_clamps_it_to_0700(tmp_path: Path) -> None:
    leaf = tmp_path / "root" / "logs"
    ensure_private_dir(leaf)
    assert leaf.is_dir()
    assert stat.S_IMODE(leaf.stat().st_mode) == 0o700


def test_clamps_newly_created_intermediate_root_to_0700(tmp_path: Path) -> None:
    root = tmp_path / "root"
    leaf = root / "logs"
    ensure_private_dir(leaf)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700


def test_tightens_preexisting_world_readable_leaf(tmp_path: Path) -> None:
    leaf = tmp_path / "root" / "logs"
    leaf.mkdir(parents=True)
    leaf.chmod(0o755)
    ensure_private_dir(leaf)
    assert stat.S_IMODE(leaf.stat().st_mode) == 0o700


def test_leaves_preexisting_restrictive_leaf_alone(tmp_path: Path) -> None:
    leaf = tmp_path / "root" / "logs"
    leaf.mkdir(parents=True)
    leaf.chmod(0o500)
    ensure_private_dir(leaf)
    assert stat.S_IMODE(leaf.stat().st_mode) == 0o500


def test_does_not_touch_preexisting_ancestor_mode(tmp_path: Path) -> None:
    """An ancestor that already existed (e.g. $HOME) keeps its mode untouched."""
    root = tmp_path / "root"
    root.mkdir()
    root.chmod(0o755)
    ensure_private_dir(root / "logs")
    assert stat.S_IMODE(root.stat().st_mode) == 0o755
