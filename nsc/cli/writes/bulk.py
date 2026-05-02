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

from dataclasses import dataclass
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


class RoutingMode(StrEnum):
    BULK = "bulk"
    LOOP = "loop"
    SINGLE = "single"


@dataclass(frozen=True)
class RoutingDecision:
    mode: RoutingMode
    records_count: int
    capability: BulkCapability
    reasoning: str


class UnsupportedBulkError(ValueError):
    """`--bulk` was passed for an endpoint whose request body is not bulk-capable."""


def route_to_bulk_or_loop(
    *,
    record_count: int,
    capability: BulkCapability,
    bulk_flag: bool | None,
) -> RoutingDecision:
    """Pick a transport mode per spec §4.5.

    Args:
        record_count: Number of records produced by the input layer (>=1).
        capability: Result of `detect_bulk_capability(operation)`.
        bulk_flag: True for `--bulk`, False for `--no-bulk`, None for default.

    Raises:
        UnsupportedBulkError: `--bulk` on a non-bulk-capable endpoint
            (capability == SINGLE).
        ValueError: record_count < 1 (caller bug).
    """
    if record_count < 1:
        raise ValueError(f"record_count must be >= 1, got {record_count}")

    if bulk_flag is True and capability is BulkCapability.SINGLE:
        raise UnsupportedBulkError(
            "--bulk requested but this endpoint does not support a list-shaped "
            "request body; rerun without --bulk (or with --no-bulk to be explicit)"
        )

    if record_count == 1:
        if bulk_flag is True:
            mode = RoutingMode.BULK
            reasoning = "explicit --bulk on a single record (sent as a 1-element array)"
        else:
            mode = RoutingMode.SINGLE
            reasoning = "single record — sent as a single object regardless of capability"
        return RoutingDecision(
            mode=mode,
            records_count=record_count,
            capability=capability,
            reasoning=reasoning,
        )

    if bulk_flag is True:
        return RoutingDecision(
            mode=RoutingMode.BULK,
            records_count=record_count,
            capability=capability,
            reasoning=(
                f"explicit --bulk: sending {record_count} records as a single "
                "array body (capability=" + capability.value + ")"
            ),
        )
    if bulk_flag is False:
        return RoutingDecision(
            mode=RoutingMode.LOOP,
            records_count=record_count,
            capability=capability,
            reasoning=(
                f"explicit --no-bulk: looping {record_count} sequential single-record requests"
            ),
        )

    if capability is BulkCapability.BULK:
        return RoutingDecision(
            mode=RoutingMode.BULK,
            records_count=record_count,
            capability=capability,
            reasoning=(
                f"endpoint is bulk-capable: sending {record_count} records as a single array body"
            ),
        )
    return RoutingDecision(
        mode=RoutingMode.LOOP,
        records_count=record_count,
        capability=capability,
        reasoning=(
            f"capability={capability.value}: looping {record_count} sequential "
            "single-record requests"
        ),
    )


__all__ = [
    "BulkCapability",
    "RoutingDecision",
    "RoutingMode",
    "UnsupportedBulkError",
    "detect_bulk_capability",
    "route_to_bulk_or_loop",
]
