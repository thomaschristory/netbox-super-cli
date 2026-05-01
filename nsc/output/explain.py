"""ExplainTrace and FieldDecision — agent contract for `--explain` (Phase 3a types).

The build_for(...) logic that populates these is added in Phase 3b. These types
are defined here in 3a so they can be imported by code under test (e.g. handlers
that pre-allocate an empty trace) without circular dependencies.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
    # `requests` is a list of dicts in 3a (no ResolvedRequest type yet); in 3b
    # this is replaced with `list[ResolvedRequest]`. The forward-compatible
    # shape uses dict-of-Any to avoid blocking 3a on 3b's types.
    requests: list[dict[str, Any]] = Field(default_factory=list)
