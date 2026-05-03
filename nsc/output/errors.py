"""Stable JSON error envelope and exit-code mapping for Phase 3+.

This module is the agent contract. Field names, values of `ErrorType`, and the
`EXIT_CODES` table must never change once shipped.
"""

from __future__ import annotations

from enum import Enum, StrEnum
from typing import Any, Literal, TextIO

from pydantic import BaseModel, ConfigDict, Field
from rich.console import Console
from rich.panel import Panel

from nsc.config.models import OutputFormat
from nsc.model.command_model import HttpMethod


class ErrorType(StrEnum):
    AUTH = "auth"
    NOT_FOUND = "not_found"
    VALIDATION = "validation"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    SERVER = "server"
    TRANSPORT = "transport"
    SCHEMA = "schema"
    CONFIG = "config"
    CLIENT = "client"
    INTERNAL = "internal"
    AMBIGUOUS_ALIAS = "ambiguous_alias"
    UNKNOWN_ALIAS = "unknown_alias"
    INPUT_ERROR = "input_error"


EXIT_CODES: dict[ErrorType, int] = {
    ErrorType.INTERNAL: 1,
    ErrorType.SCHEMA: 3,
    ErrorType.VALIDATION: 4,
    ErrorType.INPUT_ERROR: 4,
    ErrorType.SERVER: 5,
    ErrorType.CLIENT: 6,
    ErrorType.TRANSPORT: 7,
    ErrorType.AUTH: 8,
    ErrorType.NOT_FOUND: 9,
    ErrorType.CONFLICT: 10,
    ErrorType.RATE_LIMITED: 11,
    ErrorType.CONFIG: 12,
    ErrorType.AMBIGUOUS_ALIAS: 13,
    ErrorType.UNKNOWN_ALIAS: 14,
}


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ErrorEnvelope(_Frozen):
    error: str
    type: ErrorType
    endpoint: str | None = None
    method: HttpMethod | None = None
    operation_id: str | None = None
    status_code: int | None = None
    attempt_n: int | None = None
    audit_log_path: str | None = None
    record_index: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


def render_to_json(env: ErrorEnvelope) -> str:
    """Serialize the envelope as compact, one-line JSON for stdout."""
    return env.model_dump_json()


class RenderTarget(Enum):
    JSON_STDOUT = "json_stdout"
    JSON_STDERR = "json_stderr"
    RICH_STDERR = "rich_stderr"


def select_render_target(*, output_format: OutputFormat, stdout_is_tty: bool) -> RenderTarget:
    """Decide where the error envelope should render.

    Spec §4.2.3:
      - --output json (or table-piped, which falls back to json) → JSON to stdout.
      - --output table on a TTY → Rich panel to stderr.
      - Any other piped format (csv/yaml/jsonl) → JSON to stderr; stdout
        reserved for partial-success records produced by the formatter.
    """
    if output_format is OutputFormat.JSON:
        return RenderTarget.JSON_STDOUT
    if output_format is OutputFormat.TABLE:
        if stdout_is_tty:
            return RenderTarget.RICH_STDERR
        return RenderTarget.JSON_STDOUT
    return RenderTarget.JSON_STDERR


def render_to_rich_stderr(env: ErrorEnvelope, *, stream: TextIO) -> None:
    """Render the envelope as a Rich panel to the given stream (stderr in prod)."""
    console = Console(file=stream, soft_wrap=True, force_terminal=False)
    body_lines = [
        f"[bold red]{env.type.value}[/]: {env.error}",
    ]
    if env.endpoint:
        body_lines.append(f"endpoint: {env.endpoint}")
    if env.method is not None:
        body_lines.append(f"method:   {env.method.value}")
    if env.status_code is not None:
        body_lines.append(f"status:   {env.status_code}")
    if env.operation_id:
        body_lines.append(f"op:       {env.operation_id}")
    if env.attempt_n is not None:
        body_lines.append(f"attempt:  {env.attempt_n}")
    if env.audit_log_path:
        body_lines.append(f"audit:    {env.audit_log_path}")
    if env.details:
        body_lines.append(f"details:  {env.details}")
    console.print(Panel("\n".join(body_lines), title="nsc error", border_style="red"))


class ClientError(Exception):
    """A user-facing CLI usage error that should map directly to an ErrorEnvelope.

    Carries a fully-shaped envelope so the handler can re-emit it without
    re-classifying.
    """

    def __init__(self, envelope: ErrorEnvelope) -> None:
        super().__init__(envelope.error)
        self.envelope = envelope


def client_envelope(
    message: str, *, operation_id: str | None = None, **details: Any
) -> ErrorEnvelope:
    return ErrorEnvelope(
        error=message,
        type=ErrorType.CLIENT,
        operation_id=operation_id,
        details=details,
    )


def input_error_envelope(
    *,
    message: str,
    bad_lines: list[dict[str, Any]],
    operation_id: str | None = None,
) -> ErrorEnvelope:
    """Build the structured envelope for NDJSON parse failures.

    `bad_lines` is a list of `{"line": int, "reason": str}` dicts. The caller
    is responsible for capping the list at 20 entries (spec §4.4).
    """
    return ErrorEnvelope(
        error=message,
        type=ErrorType.INPUT_ERROR,
        operation_id=operation_id,
        details={"bad_lines": bad_lines},
    )


_VERB_TO_FULL_PATH_VERB: dict[str, str] = {
    "ls": "list",
    "get": "get",
    "rm": "delete",
}


def ambiguous_alias_envelope(
    *,
    verb: str,
    term: str,
    candidates: list[tuple[str, str]],
) -> ErrorEnvelope:
    """Build the envelope for an alias term that resolves to ≥2 resources.

    `candidates` is a list of `(tag, resource)` pairs; the envelope renders
    them as a list of `{"tag": ..., "resource": ...}` objects so JSON
    consumers don't have to parse positional pairs.
    """
    if verb not in _VERB_TO_FULL_PATH_VERB:
        raise ValueError(
            f"ambiguous_alias_envelope does not support verb={verb!r} "
            f"(supported: {sorted(_VERB_TO_FULL_PATH_VERB)})"
        )
    rendered = [{"tag": t, "resource": r} for t, r in candidates]
    pretty = ", ".join(f"`{t} {r}`" for t, r in candidates)
    return ErrorEnvelope(
        error=(
            f"`nsc {verb} {term}` is ambiguous — matches: {pretty}. "
            f"Use the full path: `nsc <tag> <resource> {_VERB_TO_FULL_PATH_VERB[verb]}`."
        ),
        type=ErrorType.AMBIGUOUS_ALIAS,
        details={"verb": verb, "term": term, "candidates": rendered},
    )


def unknown_alias_envelope(
    *,
    verb: str,
    term: str,
    reason: str = "no_such_resource",
) -> ErrorEnvelope:
    """Build the envelope for an alias term that resolves to zero resources.

    `reason="no_such_resource"` is the standard ls/get/rm case; the message
    suggests `nsc commands` for resource discovery. `reason="search_endpoint_unavailable"`
    is the search-specific case (schema does not expose `/api/search/`); the
    message must not suggest `nsc commands` since that wouldn't help.
    """
    if reason == "search_endpoint_unavailable":
        message = (
            "this NetBox schema does not expose `/api/search/`; "
            "`nsc search` is unavailable for this server"
        )
    else:
        message = (
            f"unknown resource `{term}` for `nsc {verb}`; "
            f"run `nsc commands` to list known resources"
        )
    return ErrorEnvelope(
        error=message,
        type=ErrorType.UNKNOWN_ALIAS,
        details={"verb": verb, "term": term, "reason": reason},
    )


ERROR_TYPE_PRECEDENCE: list[ErrorType] = [
    ErrorType.INTERNAL,
    ErrorType.TRANSPORT,
    ErrorType.SERVER,
    ErrorType.VALIDATION,
    ErrorType.CONFLICT,
    ErrorType.RATE_LIMITED,
    ErrorType.NOT_FOUND,
    ErrorType.AUTH,
    ErrorType.INPUT_ERROR,
    ErrorType.CLIENT,
    ErrorType.SCHEMA,
    ErrorType.CONFIG,
    ErrorType.AMBIGUOUS_ALIAS,
    ErrorType.UNKNOWN_ALIAS,
]
"""Strict ordering for picking a single exit code from a mixed-failure run.

Used by `--on-error continue` to map a list of per-record failures to one
final exit code. Spec §4.5.
"""


def worst_error_type(types: list[ErrorType]) -> ErrorType:
    if not types:
        raise ValueError("worst_error_type called with empty list")
    return next(t for t in ERROR_TYPE_PRECEDENCE if t in types)


def summary_envelope(
    *,
    attempted: int,
    failures: list[ErrorEnvelope],
    on_error: Literal["stop", "continue"],
    operation_id: str | None,
    total_records: int,
) -> ErrorEnvelope:
    """Build the final envelope for a multi-record loop (spec §4.5, §7.3).

    Args:
        attempted: Number of records the loop reached (success + failure).
        failures: Per-record failure envelopes (one per failed attempt).
        on_error: "stop" or "continue" — controls envelope shape.
        operation_id: Operation that the loop ran.
        total_records: Total records in the input (for partial_progress.remaining).

    Returns:
        ErrorEnvelope whose `type` equals the worst failure type by
        precedence, with `details.partial_progress = {success, failed, remaining}`.
        On "stop" sets `record_index` to the first failure's index. On "continue"
        adds `details.failures: [{record_index, type, status_code, error}, ...]`.
    """
    if not failures:
        raise ValueError("summary_envelope requires at least one failure")
    failed = len(failures)
    success = attempted - failed
    remaining = max(0, total_records - attempted)
    chosen_type = worst_error_type([f.type for f in failures])

    details: dict[str, Any] = {
        "partial_progress": {
            "success": success,
            "failed": failed,
            "remaining": remaining,
        },
        "on_error": on_error,
        "applied": True,
    }

    if on_error == "stop":
        first = failures[0]
        return ErrorEnvelope(
            error=first.error,
            type=chosen_type,
            operation_id=operation_id,
            status_code=first.status_code,
            record_index=first.record_index,
            details=details,
        )

    details["failures"] = [
        {
            "record_index": f.record_index,
            "type": f.type.value,
            "status_code": f.status_code,
            "error": f.error,
        }
        for f in failures
    ]
    return ErrorEnvelope(
        error=(f"{failed} of {attempted} records failed (worst type: {chosen_type.value})"),
        type=chosen_type,
        operation_id=operation_id,
        record_index=None,
        details=details,
    )


__all__ = [
    "ERROR_TYPE_PRECEDENCE",
    "EXIT_CODES",
    "ClientError",
    "ErrorEnvelope",
    "ErrorType",
    "RenderTarget",
    "ambiguous_alias_envelope",
    "client_envelope",
    "input_error_envelope",
    "render_to_json",
    "render_to_rich_stderr",
    "select_render_target",
    "summary_envelope",
    "unknown_alias_envelope",
    "worst_error_type",
]
