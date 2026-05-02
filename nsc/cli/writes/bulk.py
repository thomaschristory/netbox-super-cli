"""Bulk routing brain (Phase 3c).

Pure logic. No I/O, no Typer, no httpx. Three responsibilities:

1. `detect_bulk_capability(operation)` — classify a parsed Operation as
   bulk-capable, single-only, or ambiguous (spec §4.5).
2. `route_to_bulk_or_loop(...)` — combine record count, capability, and
   --bulk/--no-bulk to pick a transport mode (Task 2).
3. `run_loop(...)` — sequential, deterministic loop with --on-error
   stop|continue semantics (Task 6).
"""

from __future__ import annotations

from enum import StrEnum
from typing import assert_never

from nsc.model.command_model import Operation


class BulkCapability(StrEnum):
    BULK = "bulk"
    SINGLE = "single"
    AMBIGUOUS = "ambiguous"


def detect_bulk_capability(operation: Operation) -> BulkCapability:
    """Classify an operation by its request_body.top_level (spec §4.5).

    The builder is the upstream classifier; this function never re-parses
    raw schema. AMBIGUOUS means the builder couldn't determine a shape
    (unparseable, unresolved $ref, or no requestBody) — the handler treats
    it as single + emits a stderr warning.
    """
    body = operation.request_body
    if body is None:
        return BulkCapability.AMBIGUOUS
    match body.top_level:
        case "array" | "object_or_array":
            return BulkCapability.BULK
        case "object":
            return BulkCapability.SINGLE
        case _:
            assert_never(body.top_level)


__all__ = ["BulkCapability", "detect_bulk_capability"]
