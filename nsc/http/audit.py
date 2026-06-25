"""Audit log writers.

Two files under `~/.nsc/logs/`:
  - `last-request.json`  — single-exchange ephemeral, overwritten on every call.
  - `audit.jsonl`        — append-only, write attempts only (POST/PATCH/PUT/DELETE).

Header redaction is centralized; body redaction is opt-in via `sensitive_paths`
threaded from the schema's `RequestBodyShape.sensitive_paths` field.
"""

from __future__ import annotations

import copy
import json
import os
import stat
import sys
import tempfile
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from nsc.model.command_model import HttpMethod
from nsc.output.headers import SENSITIVE_HEADERS

DEFAULT_BODY_CAP_BYTES = 256 * 1024
DEFAULT_ROTATE_BYTES = 10 * 1024 * 1024
SCHEMA_VERSION = 1

# Audit logs hold request/response bodies verbatim; keep them owner-only,
# mirroring the 0600 treatment of config.yaml in nsc/config/writer.py.
_DIR_MODE = 0o700
_FILE_MODE = 0o600

# Serializes audit appends across threads. The bulk loop can run with N
# concurrent workers; buffered writes plus O_APPEND give no cross-thread
# atomicity for lines larger than PIPE_BUF, so we take this lock around the
# whole open/write/close to guarantee exactly one complete line per record.
_APPEND_LOCK = threading.Lock()


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AuditEntry(_Frozen):
    timestamp: str
    operation_id: str | None = None
    method: HttpMethod
    url: str
    request_headers: dict[str, str] = Field(default_factory=dict)
    request_query: dict[str, Any] = Field(default_factory=dict)
    request_body: Any = None
    sensitive_paths: tuple[str, ...] = ()
    response_status_code: int | None = None
    response_headers: dict[str, str] = Field(default_factory=dict)
    response_body: Any = None
    duration_ms: int | None = None
    attempt_n: int = 1
    final_attempt: bool = True
    error_kind: str | None = None
    dry_run: bool = False
    preflight_blocked: bool = False
    record_indices: list[int] = Field(default_factory=list)
    applied: bool = False
    explain: bool = False


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: ("<redacted>" if k.lower() in SENSITIVE_HEADERS else v) for k, v in headers.items()}


def redact_body(body: Any, sensitive_paths: Sequence[str]) -> Any:
    """Return a deep-copy of `body` with all `sensitive_paths` rewritten to `"<redacted>"`.

    Path semantics:
      - Each path is a dotted string (e.g., "auth.password"). Empty paths are ignored.
      - The walker descends into dicts by key.
      - When it encounters a list, it applies the remainder of the path to every element.
      - A missing key on the walk is a no-op (the schema may declare optional fields).
      - A non-mapping/non-list intermediate aborts that path safely.
    """
    if body is None or not sensitive_paths:
        return body
    out = copy.deepcopy(body)
    for path in sensitive_paths:
        if not path:
            continue
        _apply_redaction(out, path.split("."))
    return out


def _apply_redaction(node: Any, parts: list[str]) -> None:
    if not parts:
        return
    head, *tail = parts
    if isinstance(node, list):
        for item in node:
            _apply_redaction(item, parts)
        return
    if not isinstance(node, dict):
        return
    if head not in node:
        return
    if not tail:
        node[head] = "<redacted>"
        return
    _apply_redaction(node[head], tail)


def truncate_body(body: Any, *, cap_bytes: int = DEFAULT_BODY_CAP_BYTES) -> tuple[Any, bool]:
    """Return (possibly-truncated body, was_truncated)."""
    if body is None:
        return None, False
    serialized = json.dumps(body, default=str).encode("utf-8")
    if len(serialized) <= cap_bytes:
        return body, False
    return {"_truncated": True, "_size_bytes": len(serialized)}, True


def _to_dict(entry: AuditEntry) -> dict[str, Any]:
    """Serialize to the wire shape documented in spec §4.3."""
    req_body, req_trunc = truncate_body(redact_body(entry.request_body, entry.sensitive_paths))
    resp_body, resp_trunc = truncate_body(entry.response_body)
    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp": entry.timestamp,
        "operation_id": entry.operation_id,
        "method": entry.method.value,
        "url": entry.url,
        "request": {
            "headers": redact_headers(entry.request_headers),
            "query": entry.request_query,
            "body": req_body,
            "body_truncated": req_trunc,
        },
        "response": (
            None
            if entry.response_status_code is None
            else {
                "status_code": entry.response_status_code,
                "headers": redact_headers(entry.response_headers),
                "body": resp_body,
                "body_truncated": resp_trunc,
            }
        ),
        "duration_ms": entry.duration_ms,
        "attempt_n": entry.attempt_n,
        "final_attempt": entry.final_attempt,
        "error_kind": entry.error_kind,
        "dry_run": entry.dry_run,
        "preflight_blocked": entry.preflight_blocked,
        "record_indices": entry.record_indices,
        "applied": entry.applied,
        "explain": entry.explain,
    }


def _warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def _ensure_private_dir(directory: Path) -> None:
    """Ensure `directory` exists and is owner-only.

    Tightens an existing world/group-accessible dir too (e.g. a `~/.nsc/logs`
    left 0755 by an older nsc version or a permissive umask), but leaves an
    already-restrictive dir alone so a deliberately read-only dir still surfaces
    a write failure rather than being silently reopened.
    """
    directory.mkdir(parents=True, exist_ok=True)
    if stat.S_IMODE(directory.stat().st_mode) & 0o077:
        os.chmod(directory, _DIR_MODE)


def write_last_request(entry: AuditEntry, *, path: Path) -> None:
    """Atomically overwrite `path` with the entry. Failures emit a stderr warning."""
    try:
        _ensure_private_dir(path.parent)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as tmp:
            json.dump(_to_dict(entry), tmp)
            tmp_path = Path(tmp.name)
        os.chmod(tmp_path, _FILE_MODE)
        os.replace(tmp_path, path)
    except OSError as exc:
        _warn(f"could not write audit log {path}: {exc}")


def append_audit_jsonl(
    entry: AuditEntry,
    *,
    path: Path,
    rotate_bytes: int = DEFAULT_ROTATE_BYTES,
) -> None:
    """Append the entry as a single line. Rotate to `path.1` when over the threshold.

    Thread-safe: the entire rotate/open/write/close runs under `_APPEND_LOCK`
    so concurrent bulk-loop workers cannot interleave partial lines or race the
    rotation check.
    """
    line = json.dumps(_to_dict(entry)) + "\n"
    with _APPEND_LOCK:
        try:
            _ensure_private_dir(path.parent)
            if path.exists() and path.stat().st_size > rotate_bytes:
                rolled = path.with_suffix(path.suffix + ".1")
                os.replace(path, rolled)
                # os.replace keeps the source mode; force 0600 so a pre-existing
                # world-readable log does not carry that mode onto the rotated copy.
                os.chmod(rolled, _FILE_MODE)
            # os.open with _FILE_MODE sets owner-only perms at creation (umask can
            # only clear bits, never widen 0600); chmod fixes any pre-existing file.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, _FILE_MODE)
            with os.fdopen(fd, "a", encoding="utf-8") as fh:
                os.chmod(path, _FILE_MODE)
                fh.write(line)
        except OSError as exc:
            _warn(f"could not append audit log {path}: {exc}")
