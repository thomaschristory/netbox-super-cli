"""Round-trip-preserving writes for `~/.nsc/config.yaml`.

This module is the write counterpart to `nsc/config/loader.py`. It will expose:

* `load_round_trip(path)` / `dump_round_trip(doc)` — parse and serialize using
  the same `YAML(typ="rt")` configured with the `!env` constructor.
* `set_path(doc, dotted, value)` / `unset_path(doc, dotted)` — dotted-path
  mutators that preserve comments and key order.
* `atomic_write(path, text)` — tempfile + fsync + os.replace, 0600 mode.
* `acquire_lock(path)` — best-effort `flock` context manager.

This file currently implements only the atomic-write + lock primitives; the
round-trip and mutator helpers land in a follow-up task.
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

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
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError as exc:
            _log.debug("flock failed on %s (%s); proceeding without it", lock_path, exc)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
