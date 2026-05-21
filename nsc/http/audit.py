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
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from nsc.model.command_model import HttpMethod
from nsc.output.headers import SENSITIVE_HEADERS

DEFAULT_BODY_CAP_BYTES = 256 * 1024
DEFAULT_ROTATE_BYTES = 10 * 1024 * 1024
SCHEMA_VERSION = 1


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
                "headers": dict(entry.response_headers),
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


def write_last_request(entry: AuditEntry, *, path: Path) -> None:
    """Atomically overwrite `path` with the entry. Failures emit a stderr warning."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as tmp:
            json.dump(_to_dict(entry), tmp)
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, path)
    except OSError as exc:
        _warn(f"could not write audit log {path}: {exc}")


def append_audit_jsonl(
    entry: AuditEntry,
    *,
    path: Path,
    rotate_bytes: int = DEFAULT_ROTATE_BYTES,
) -> None:
    """Append the entry as a single line. Rotate to `path.1` when over the threshold."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > rotate_bytes:
            rolled = path.with_suffix(path.suffix + ".1")
            os.replace(path, rolled)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_to_dict(entry)))
            fh.write("\n")
    except OSError as exc:
        _warn(f"could not append audit log {path}: {exc}")
