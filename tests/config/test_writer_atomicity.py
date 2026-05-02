"""Atomic-write + flock primitives for nsc/config/writer.py."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from nsc.config.writer import acquire_lock, atomic_write


def test_atomic_write_creates_file_with_0600_permissions(tmp_path: Path) -> None:
    target = tmp_path / "config.yaml"
    atomic_write(target, "hello: world\n")
    assert target.read_text(encoding="utf-8") == "hello: world\n"
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600


def test_atomic_write_replaces_existing_file_atomically(tmp_path: Path) -> None:
    target = tmp_path / "config.yaml"
    target.write_text("old: value\n", encoding="utf-8")
    atomic_write(target, "new: value\n")
    assert target.read_text(encoding="utf-8") == "new: value\n"


def test_atomic_write_leaves_original_intact_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "config.yaml"
    target.write_text("original: value\n", encoding="utf-8")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError, match="simulated replace failure"):
        atomic_write(target, "new: value\n")

    assert target.read_text(encoding="utf-8") == "original: value\n"
    siblings = [p.name for p in tmp_path.iterdir()]
    assert siblings == ["config.yaml"]


def test_acquire_lock_is_a_context_manager(tmp_path: Path) -> None:
    target = tmp_path / "config.yaml"
    target.write_text("x: 1\n", encoding="utf-8")
    with acquire_lock(target):
        pass


def test_acquire_lock_does_not_raise_when_target_missing(tmp_path: Path) -> None:
    """Lock acquisition is best-effort; a missing file is fine (writer creates it)."""
    target = tmp_path / "does-not-exist.yaml"
    with acquire_lock(target):
        pass
