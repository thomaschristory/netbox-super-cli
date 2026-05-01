"""ExplainTrace and FieldDecision — agent contract for `--explain`.

Phase 3a defined the types; Phase 3b adds `build_for(...)` and renderers.

The schema_version on ExplainTrace is part of the agent contract: bump it on
any breaking change to the JSON shape.
"""

from __future__ import annotations

from typing import Any, Literal, TextIO

from pydantic import BaseModel, ConfigDict, Field
from rich.console import Console
from rich.panel import Panel

from nsc.cli.writes.apply import ResolvedRequest
from nsc.cli.writes.input import RawWriteInput
from nsc.cli.writes.preflight import PreflightResult
from nsc.model.command_model import Operation

DECISION_CAP = 200


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FieldDecision(_Frozen):
    field_path: str
    source: Literal["file", "field_flag", "default", "schema_cast"]
    raw_value: Any
    resolved_value: Any
    note: str | None = None


class ExplainTrace(_Frozen):
    schema_version: int = 1
    operation_id: str
    operation_summary: str | None = None
    method_reasoning: str
    url_reasoning: str
    bulk_reasoning: str | None = None
    decisions: list[FieldDecision] = Field(default_factory=list)
    decisions_truncated: bool = False
    requests: list[ResolvedRequest] = Field(default_factory=list)
    preflight: PreflightResult | None = None

    @classmethod
    def build_for(
        cls,
        operation: Operation,
        raw: RawWriteInput,
        preflight: PreflightResult,
        requests: list[ResolvedRequest],
        *,
        field_overrides: set[str],
    ) -> ExplainTrace:
        decisions, truncated = _build_decisions(raw, requests, field_overrides)
        return cls(
            operation_id=operation.operation_id,
            operation_summary=operation.summary,
            method_reasoning=_method_reasoning(operation),
            url_reasoning=_url_reasoning(operation, requests),
            bulk_reasoning=None,
            decisions=decisions,
            decisions_truncated=truncated,
            requests=list(requests),
            preflight=preflight,
        )


def _build_decisions(
    raw: RawWriteInput,
    requests: list[ResolvedRequest],
    field_overrides: set[str],
) -> tuple[list[FieldDecision], bool]:
    decisions: list[FieldDecision] = []
    for index, record in enumerate(raw.records):
        resolved_body = _resolved_body_for_record(requests, index)
        for key, raw_value in record.items():
            if len(decisions) >= DECISION_CAP:
                return decisions, True
            resolved_value = (
                resolved_body.get(key) if isinstance(resolved_body, dict) else raw_value
            )
            source = _decide_source(key, field_overrides, raw)
            note = _decide_note(raw_value, resolved_value, key, field_overrides)
            decisions.append(
                FieldDecision(
                    field_path=_record_path(index, key, raw),
                    source=source,
                    raw_value=raw_value,
                    resolved_value=resolved_value,
                    note=note,
                )
            )
    return decisions, False


def _resolved_body_for_record(
    requests: list[ResolvedRequest], record_index: int
) -> dict[str, Any] | None:
    for r in requests:
        if record_index in r.record_indices and isinstance(r.body, dict):
            return r.body
    return None


def _decide_source(
    key: str, field_overrides: set[str], raw: RawWriteInput
) -> Literal["file", "field_flag", "default", "schema_cast"]:
    if key in field_overrides:
        return "field_flag"
    if raw.source == "fields_only":
        return "field_flag"
    return "file"


def _decide_note(
    raw_value: Any, resolved_value: Any, key: str, field_overrides: set[str]
) -> str | None:
    parts: list[str] = []
    if key in field_overrides and raw_value is not None:
        parts.append("override from --field flag")
    if raw_value != resolved_value:
        parts.append(f"schema_cast: {type(raw_value).__name__} → {type(resolved_value).__name__}")
    return "; ".join(parts) if parts else None


def _record_path(index: int, key: str, raw: RawWriteInput) -> str:
    return f"records[{index}].{key}" if raw.is_explicit_list else key


def _method_reasoning(operation: Operation) -> str:
    return f"{operation.http_method.value} per OpenAPI operation {operation.operation_id!r}"


def _url_reasoning(operation: Operation, requests: list[ResolvedRequest]) -> str:
    if not requests:
        return f"path template {operation.path!r}; no path vars resolved"
    request = requests[0]
    if request.path_vars:
        return f"path template {operation.path!r} with vars {request.path_vars}"
    return f"path template {operation.path!r}; no path vars"


def render_to_json(trace: ExplainTrace) -> str:
    return trace.model_dump_json()


def render_to_rich_stdout(trace: ExplainTrace, *, stream: TextIO) -> None:
    console = Console(file=stream, soft_wrap=True, force_terminal=False)
    body = [
        f"[bold cyan]operation:[/] {trace.operation_id}",
    ]
    if trace.operation_summary:
        body.append(f"summary:   {trace.operation_summary}")
    body.append(f"method:    {trace.method_reasoning}")
    body.append(f"url:       {trace.url_reasoning}")
    if trace.bulk_reasoning:
        body.append(f"bulk:      {trace.bulk_reasoning}")
    for r in trace.requests:
        body.append(f"  → {r.method.value} {r.url}")
        if r.body is not None:
            body.append(f"    body: {r.body}")
    if trace.preflight is not None and not trace.preflight.ok:
        body.append("preflight: [red]FAIL[/]")
        for issue in trace.preflight.issues:
            loc = f"records[{issue.record_index}].{issue.field_path}"
            body.append(f"  [{issue.kind}] {loc}: {issue.message}")
    elif trace.preflight is not None:
        body.append("preflight: [green]OK[/]")
    if trace.decisions:
        body.append("decisions:")
        for d in trace.decisions:
            extra = f" — {d.note}" if d.note else ""
            body.append(
                f"  {d.field_path}  [{d.source}]  {d.raw_value!r} → {d.resolved_value!r}{extra}"
            )
        if trace.decisions_truncated:
            body.append(f"  … truncated at {DECISION_CAP} entries")
    console.print(Panel("\n".join(body), title="nsc explain", border_style="cyan"))


__all__ = [
    "DECISION_CAP",
    "ExplainTrace",
    "FieldDecision",
    "render_to_json",
    "render_to_rich_stdout",
]
