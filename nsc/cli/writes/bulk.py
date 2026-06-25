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

import threading
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, assert_never

from nsc.model.command_model import Operation
from nsc.output.errors import ErrorEnvelope

if TYPE_CHECKING:
    from nsc.cli.writes.apply import ResolvedRequest


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
                f"array body (capability={capability.value})"
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


@dataclass(frozen=True)
class LoopAttempt:
    request: ResolvedRequest
    response: dict[str, Any] | None
    failure: ErrorEnvelope | None


@dataclass(frozen=True)
class LoopResult:
    attempts: list[LoopAttempt]

    @property
    def attempted(self) -> int:
        return len(self.attempts)

    @property
    def successes(self) -> int:
        return sum(1 for a in self.attempts if a.failure is None)

    @property
    def failures(self) -> list[ErrorEnvelope]:
        return [a.failure for a in self.attempts if a.failure is not None]


SendOne = Callable[[Operation, "ResolvedRequest"], dict[str, Any]]
AuditAttempt = Callable[["ResolvedRequest", dict[str, Any] | None, Exception | None], None]
ToEnvelope = Callable[[Exception], ErrorEnvelope]


def run_loop(
    requests: list[ResolvedRequest],
    *,
    operation: Operation,
    on_error: Literal["stop", "continue"],
    send_one: SendOne,
    audit_attempt: AuditAttempt,
    to_envelope: ToEnvelope,
    workers: int = 1,
) -> LoopResult:
    """Send N requests; collect successes and failures (spec §4.5).

    With `workers == 1` the loop is sequential and deterministic: requests run
    in input order and audit fires once per attempted request in that order.
    With `workers > 1` up to `workers` requests are in flight concurrently via
    a thread pool (the NetBox client is sync httpx, so threads — not asyncio —
    are the right mechanism). Each record's send/retry/audit is independent.

    On `on_error="stop"` the loop stops submitting new work after the first
    failure; in-flight requests are allowed to complete (cancelling them would
    leave partially-applied writes whose outcome the audit log could not
    record). On `"continue"` every request is attempted.

    Audit fires once per attempted request (success and failure). Under
    concurrency the audit *callback* may run from worker threads; the injected
    writer must be thread-safe (the production audit writer serializes appends).

    `send_one` does the wire send; `audit_attempt` writes the audit entry;
    `to_envelope` converts a raised exception into an ErrorEnvelope. Callers
    inject these so this loop has no dependency on httpx or the audit module.
    """
    if workers < 1:
        raise ValueError(f"workers must be >= 1, got {workers}")
    if workers == 1:
        return _run_loop_sequential(
            requests,
            operation=operation,
            on_error=on_error,
            send_one=send_one,
            audit_attempt=audit_attempt,
            to_envelope=to_envelope,
        )
    return _run_loop_concurrent(
        requests,
        operation=operation,
        on_error=on_error,
        send_one=send_one,
        audit_attempt=audit_attempt,
        to_envelope=to_envelope,
        workers=workers,
    )


def _run_loop_sequential(
    requests: list[ResolvedRequest],
    *,
    operation: Operation,
    on_error: Literal["stop", "continue"],
    send_one: SendOne,
    audit_attempt: AuditAttempt,
    to_envelope: ToEnvelope,
) -> LoopResult:
    attempts: list[LoopAttempt] = []
    for request in requests:
        try:
            response = send_one(operation, request)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            failure = to_envelope(exc)
            audit_attempt(request, None, exc)
            attempts.append(LoopAttempt(request=request, response=None, failure=failure))
            if on_error == "stop":
                break
        else:
            audit_attempt(request, response, None)
            attempts.append(LoopAttempt(request=request, response=response, failure=None))
    return LoopResult(attempts=attempts)


def _attempt_one(
    request: ResolvedRequest,
    *,
    operation: Operation,
    send_one: SendOne,
    audit_attempt: AuditAttempt,
    to_envelope: ToEnvelope,
) -> LoopAttempt:
    try:
        response = send_one(operation, request)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        audit_attempt(request, None, exc)
        return LoopAttempt(request=request, response=None, failure=to_envelope(exc))
    audit_attempt(request, response, None)
    return LoopAttempt(request=request, response=response, failure=None)


def _run_loop_concurrent(
    requests: list[ResolvedRequest],
    *,
    operation: Operation,
    on_error: Literal["stop", "continue"],
    send_one: SendOne,
    audit_attempt: AuditAttempt,
    to_envelope: ToEnvelope,
    workers: int,
) -> LoopResult:
    pending = iter(requests)
    stop = threading.Event()

    def run(request: ResolvedRequest) -> LoopAttempt:
        return _attempt_one(
            request,
            operation=operation,
            send_one=send_one,
            audit_attempt=audit_attempt,
            to_envelope=to_envelope,
        )

    attempts: list[LoopAttempt] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        in_flight: set[Future[LoopAttempt]] = set()
        for request in pending:
            in_flight.add(pool.submit(run, request))
            if len(in_flight) < workers:
                continue
            done, in_flight = wait(in_flight, return_when=FIRST_COMPLETED)
            for future in done:
                attempt = future.result()
                attempts.append(attempt)
                if attempt.failure is not None and on_error == "stop":
                    stop.set()
            if stop.is_set():
                break
        for future in in_flight:
            attempts.append(future.result())
    return LoopResult(attempts=attempts)


__all__ = [
    "AuditAttempt",
    "BulkCapability",
    "LoopAttempt",
    "LoopResult",
    "RoutingDecision",
    "RoutingMode",
    "SendOne",
    "ToEnvelope",
    "UnsupportedBulkError",
    "detect_bulk_capability",
    "route_to_bulk_or_loop",
    "run_loop",
]
