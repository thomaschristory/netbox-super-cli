"""Round-trip-preserving writes for `~/.nsc/config.yaml`.

This module is the write counterpart to `nsc/config/loader.py`. It exposes:

* `load_round_trip(path)` / `dump_round_trip(doc)` — parse and serialize using
  `YAML(typ="rt")`. Unlike the loader, the writer's YAML does NOT register an
  `!env` constructor, so tagged scalars round-trip through unchanged.
* `set_path(doc, dotted, value)` / `unset_path(doc, dotted)` — dotted-path
  mutators that preserve comments and key order.
* `atomic_write(path, text)` — tempfile + fsync + os.replace, 0600 mode.
* `acquire_lock(path)` — best-effort `flock` context manager.
"""

from __future__ import annotations

import contextlib
import io
import logging
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, TaggedScalar
from ruamel.yaml.constructor import BaseConstructor
from ruamel.yaml.nodes import ScalarNode

_log = logging.getLogger(__name__)
_FILE_MODE = 0o600


def atomic_write(path: Path, text: str) -> None:
    """Write `text` to `path` atomically with 0600 permissions.

    Strategy: create a sibling temp file in the same directory, fsync it,
    chmod 0600, then `os.replace` it onto the target. On any failure
    before or during `os.replace`, the original file is untouched and
    the temp file is cleaned up.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp = Path(tmp_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, _FILE_MODE)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise


@contextlib.contextmanager
def acquire_lock(path: Path) -> Iterator[None]:
    """Best-effort exclusive lock on `path`'s sidecar lock file.

    Uses `fcntl.flock` on POSIX; on platforms without it (or on NFS-style
    filesystems where it is a no-op), logs a debug note and yields without
    blocking. The lock is sidecar-on-purpose (`<name>.lock`) so we never
    truncate the target file via locking.
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl  # noqa: PLC0415  # platform-conditional: absent on Windows.
    except ImportError:
        _log.debug("fcntl unavailable; proceeding without flock on %s", path)
        yield
        return

    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            locked = True
        except OSError as exc:
            _log.debug("flock failed on %s (%s); proceeding without it", lock_path, exc)
        yield
    finally:
        if locked:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class ConfigWriteError(Exception):
    """Raised when a config write violates the dotted-path contract."""


def _construct_env_tag(_loader: BaseConstructor, node: ScalarNode) -> TaggedScalar:
    return TaggedScalar(value=str(node.value), style=None, tag="!env")


def _writer_yaml() -> YAML:
    """Round-trip YAML for the writer.

    The writer round-trips the *file* surface, so a `!env FOO` scalar must
    come back out as `!env FOO`, not as the resolved string. We override the
    `!env` constructor with one that returns a `TaggedScalar`, preserving the
    tag through dump.

    ruamel.yaml's `add_constructor` registers at the class level on
    `RoundTripConstructor`, so the most recent registration wins for every
    later `YAML(typ="rt")` instance in the same process. Both this factory and
    `nsc.config.loader._round_trip_yaml` register fresh on every call to
    ensure the local intent wins, but tests that interleave loader and writer
    parsers can still observe the cross-instance side effect — keep that in
    mind when adding tests that depend on `!env` resolution semantics.
    """
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.constructor.add_constructor("!env", _construct_env_tag)
    return yaml


def load_round_trip(path: Path) -> CommentedMap:
    """Parse `path` into a `CommentedMap` ready for in-place mutation.

    Returns an empty `CommentedMap` if the file is missing or empty so callers
    can `set_path` into a fresh doc.
    """
    if not path.exists():
        return CommentedMap()
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return CommentedMap()
    doc = _writer_yaml().load(io.StringIO(text))
    if doc is None:
        return CommentedMap()
    if not isinstance(doc, CommentedMap):
        raise ConfigWriteError(f"{path}: top-level value must be a mapping")
    return doc


def dump_round_trip(doc: CommentedMap) -> str:
    """Serialize `doc` back to YAML, preserving comments, order, and tags."""
    buf = io.StringIO()
    _writer_yaml().dump(doc, buf)
    return buf.getvalue()


def _split(dotted: str) -> list[str]:
    parts = [p for p in dotted.split(".") if p]
    if not parts:
        raise ConfigWriteError("path must be non-empty")
    return parts


def set_path(doc: CommentedMap, dotted: str, value: Any) -> None:
    """Set `doc[a][b]...[leaf] = value`, creating intermediate maps as needed.

    Refuses to descend past a scalar (would discard data) or to overwrite a
    map with a scalar at the leaf (likewise). Both raise `ConfigWriteError`.
    """
    parts = _split(dotted)
    cursor: Any = doc
    for i, key in enumerate(parts[:-1]):
        nxt = cursor.get(key) if isinstance(cursor, CommentedMap) else None
        if nxt is None:
            nxt = CommentedMap()
            cursor[key] = nxt
        elif not isinstance(nxt, CommentedMap):
            joined = ".".join(parts[: i + 1])
            raise ConfigWriteError(
                f"cannot descend into scalar at {joined!r}; "
                f"refusing to overwrite a value with a map"
            )
        cursor = nxt
    leaf_key = parts[-1]
    existing = cursor.get(leaf_key) if isinstance(cursor, CommentedMap) else None
    if isinstance(existing, CommentedMap):
        raise ConfigWriteError(f"refusing to overwrite map at {dotted!r} with a scalar value")
    cursor[leaf_key] = value


def unset_path(doc: CommentedMap, dotted: str) -> None:
    """Remove `doc[a][b]...[leaf]` and prune empty parent maps.

    No-op if any segment is missing. Pruning stops at non-empty parents.
    """
    parts = _split(dotted)
    chain: list[tuple[CommentedMap, str]] = []
    cursor: Any = doc
    for key in parts[:-1]:
        if not isinstance(cursor, CommentedMap) or key not in cursor:
            return
        chain.append((cursor, key))
        cursor = cursor[key]
    leaf_key = parts[-1]
    if not isinstance(cursor, CommentedMap) or leaf_key not in cursor:
        return
    del cursor[leaf_key]
    for parent, key in reversed(chain):
        if isinstance(parent[key], CommentedMap) and len(parent[key]) == 0:
            del parent[key]
        else:
            break
