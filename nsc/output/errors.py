"""Stable JSON error envelope and exit-code mapping for Phase 3+.

This module is the agent contract. Field names, values of `ErrorType`, and the
`EXIT_CODES` table must never change once shipped.
"""

from __future__ import annotations

from enum import Enum, StrEnum
from typing import Any, TextIO

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


EXIT_CODES: dict[ErrorType, int] = {
    ErrorType.INTERNAL: 1,
    ErrorType.SCHEMA: 3,
    ErrorType.VALIDATION: 4,
    ErrorType.SERVER: 5,
    ErrorType.CLIENT: 6,
    ErrorType.TRANSPORT: 7,
    ErrorType.AUTH: 8,
    ErrorType.NOT_FOUND: 9,
    ErrorType.CONFLICT: 10,
    ErrorType.RATE_LIMITED: 11,
    ErrorType.CONFIG: 12,
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
