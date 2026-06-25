"""Phase 3c — bulk capability detection and routing tests."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Literal

import pytest

from nsc.cli.writes.apply import ResolvedRequest
from nsc.cli.writes.bulk import (
    BulkCapability,
    LoopAttempt,
    RoutingMode,
    UnsupportedBulkError,
    detect_bulk_capability,
    route_to_bulk_or_loop,
    run_loop,
)
from nsc.model.command_model import (
    HttpMethod,
    Operation,
    RequestBodyShape,
)
from nsc.output.errors import ErrorEnvelope, ErrorType


def _op(top_level: Literal["object", "array", "object_or_array"] | None) -> Operation:
    body: RequestBodyShape | None
    body = None if top_level is None else RequestBodyShape(top_level=top_level)
    return Operation(
        operation_id="x_create",
        http_method=HttpMethod.POST,
        path="/api/x/",
        request_body=body,
    )


@pytest.mark.parametrize(
    ("top_level", "expected"),
    [
        ("array", BulkCapability.BULK),
        ("object_or_array", BulkCapability.BULK),
        ("object", BulkCapability.SINGLE),
        (None, BulkCapability.AMBIGUOUS),
    ],
)
def test_detect_bulk_capability(top_level: str | None, expected: BulkCapability) -> None:
    assert detect_bulk_capability(_op(top_level)) is expected


def test_bulk_capability_values_are_stable_strings() -> None:
    # Agent contract — these strings appear in ExplainTrace.bulk_reasoning
    # and in client-error envelopes. Don't rename.
    assert BulkCapability.BULK.value == "bulk"
    assert BulkCapability.SINGLE.value == "single"
    assert BulkCapability.AMBIGUOUS.value == "ambiguous"


def test_routing_single_record_default_is_single() -> None:
    decision = route_to_bulk_or_loop(
        record_count=1,
        capability=BulkCapability.BULK,
        bulk_flag=None,
    )
    assert decision.mode is RoutingMode.SINGLE
    assert decision.records_count == 1
    assert "single record" in decision.reasoning.lower()


def test_routing_single_record_with_bulk_flag_is_bulk() -> None:
    decision = route_to_bulk_or_loop(
        record_count=1,
        capability=BulkCapability.BULK,
        bulk_flag=True,
    )
    assert decision.mode is RoutingMode.BULK
    assert "explicit --bulk" in decision.reasoning


def test_routing_n_records_default_with_bulk_capability_is_bulk() -> None:
    decision = route_to_bulk_or_loop(
        record_count=5,
        capability=BulkCapability.BULK,
        bulk_flag=None,
    )
    assert decision.mode is RoutingMode.BULK


def test_routing_n_records_default_without_bulk_capability_is_loop() -> None:
    decision = route_to_bulk_or_loop(
        record_count=5,
        capability=BulkCapability.SINGLE,
        bulk_flag=None,
    )
    assert decision.mode is RoutingMode.LOOP


def test_routing_n_records_no_bulk_flag_is_loop_even_when_capable() -> None:
    decision = route_to_bulk_or_loop(
        record_count=5,
        capability=BulkCapability.BULK,
        bulk_flag=False,
    )
    assert decision.mode is RoutingMode.LOOP
    assert "explicit --no-bulk" in decision.reasoning


def test_routing_bulk_flag_on_non_bulk_endpoint_raises() -> None:
    with pytest.raises(UnsupportedBulkError) as excinfo:
        route_to_bulk_or_loop(
            record_count=5,
            capability=BulkCapability.SINGLE,
            bulk_flag=True,
        )
    msg = str(excinfo.value)
    assert "--bulk" in msg
    assert "does not support" in msg.lower()


def test_routing_ambiguous_capability_with_default_falls_back_to_loop_for_n() -> None:
    # AMBIGUOUS means the builder couldn't classify; treat as single (loop for N).
    decision = route_to_bulk_or_loop(
        record_count=5,
        capability=BulkCapability.AMBIGUOUS,
        bulk_flag=None,
    )
    assert decision.mode is RoutingMode.LOOP
    assert "ambiguous" in decision.reasoning.lower()


def test_routing_ambiguous_capability_with_bulk_flag_attempts_bulk() -> None:
    # User explicitly asked for bulk; honor it (server will arbitrate).
    decision = route_to_bulk_or_loop(
        record_count=5,
        capability=BulkCapability.AMBIGUOUS,
        bulk_flag=True,
    )
    assert decision.mode is RoutingMode.BULK
    assert "ambiguous" in decision.reasoning.lower()


def test_routing_zero_records_raises() -> None:
    # Empty input is rejected at the input layer (spec §4.7); guard here too
    # so callers never construct a meaningless decision.
    with pytest.raises(ValueError, match=r"record_count must be >= 1"):
        route_to_bulk_or_loop(
            record_count=0,
            capability=BulkCapability.BULK,
            bulk_flag=None,
        )


def _req(index: int) -> ResolvedRequest:
    return ResolvedRequest(
        method=HttpMethod.POST,
        url="https://nb.example/api/x/",
        body={"i": index},
        operation_id="x_create",
        record_indices=[index],
    )


def _ok(_op: object, _req: ResolvedRequest) -> dict[str, object]:
    return {"id": 1}


def _fail_at(
    target: int, err_type: ErrorType = ErrorType.VALIDATION, status: int = 400
) -> Callable[[object, ResolvedRequest], dict[str, object]]:
    def send(_op: object, request: ResolvedRequest) -> dict[str, object]:
        if request.record_indices == [target]:
            raise _SimulatedFailure(
                ErrorEnvelope(
                    error=f"server returned {status}",
                    type=err_type,
                    status_code=status,
                    record_index=target,
                    operation_id="x_create",
                )
            )
        return {"id": 1}

    return send


class _SimulatedFailure(Exception):
    def __init__(self, envelope: ErrorEnvelope) -> None:
        super().__init__(envelope.error)
        self.envelope = envelope


def _to_envelope(exc: Exception) -> ErrorEnvelope:
    assert isinstance(exc, _SimulatedFailure)
    return exc.envelope


def test_run_loop_all_success_sends_every_request() -> None:
    audited: list[tuple[int, bool]] = []

    def audit(req: ResolvedRequest, _resp: dict | None, err: Exception | None) -> None:
        audited.append((req.record_indices[0], err is None))

    requests = [_req(0), _req(1), _req(2)]
    result = run_loop(
        requests,
        operation=None,  # type: ignore[arg-type]  # send_one ignores op in this test
        on_error="stop",
        send_one=_ok,
        audit_attempt=audit,
        to_envelope=_to_envelope,
    )
    assert result.attempted == 3
    assert result.successes == 3
    assert result.failures == []
    assert audited == [(0, True), (1, True), (2, True)]


def test_run_loop_stop_aborts_on_first_failure() -> None:
    audited: list[tuple[int, bool]] = []

    def audit(req: ResolvedRequest, _resp: dict | None, err: Exception | None) -> None:
        audited.append((req.record_indices[0], err is None))

    result = run_loop(
        [_req(0), _req(1), _req(2), _req(3), _req(4)],
        operation=None,  # type: ignore[arg-type]
        on_error="stop",
        send_one=_fail_at(2),
        audit_attempt=audit,
        to_envelope=_to_envelope,
    )
    assert result.attempted == 3  # 0 OK, 1 OK, 2 fail → stop
    assert result.successes == 2
    assert len(result.failures) == 1
    assert result.failures[0].record_index == 2
    assert result.failures[0].type is ErrorType.VALIDATION
    # Audit fired for the 2 successes AND the failure (one entry per attempt).
    assert audited == [(0, True), (1, True), (2, False)]


def test_run_loop_continue_attempts_every_record() -> None:
    audited: list[tuple[int, bool]] = []

    def audit(req: ResolvedRequest, _resp: dict | None, err: Exception | None) -> None:
        audited.append((req.record_indices[0], err is None))

    def mixed(_op: object, request: ResolvedRequest) -> dict[str, object]:
        idx = request.record_indices[0]
        if idx == 0:
            raise _SimulatedFailure(
                ErrorEnvelope(
                    error="bad",
                    type=ErrorType.VALIDATION,
                    status_code=400,
                    record_index=0,
                    operation_id="x_create",
                )
            )
        if idx == 2:
            raise _SimulatedFailure(
                ErrorEnvelope(
                    error="auth",
                    type=ErrorType.AUTH,
                    status_code=401,
                    record_index=2,
                    operation_id="x_create",
                )
            )
        return {"id": 1}

    result = run_loop(
        [_req(i) for i in range(5)],
        operation=None,  # type: ignore[arg-type]
        on_error="continue",
        send_one=mixed,
        audit_attempt=audit,
        to_envelope=_to_envelope,
    )
    assert result.attempted == 5
    assert result.successes == 3
    assert [f.record_index for f in result.failures] == [0, 2]
    # All five attempts audited (3 successes, 2 failures).
    assert [a[0] for a in audited] == [0, 1, 2, 3, 4]
    assert [a[1] for a in audited] == [False, True, False, True, True]


def test_run_loop_rejects_workers_below_one() -> None:
    with pytest.raises(ValueError, match=r"workers must be >= 1"):
        run_loop(
            [_req(0)],
            operation=None,  # type: ignore[arg-type]
            on_error="continue",
            send_one=_ok,
            audit_attempt=lambda *_a: None,
            to_envelope=_to_envelope,
            workers=0,
        )


def test_run_loop_workers_one_is_sequential_in_order() -> None:
    audited: list[tuple[int, bool]] = []

    def audit(req: ResolvedRequest, _resp: dict | None, err: Exception | None) -> None:
        audited.append((req.record_indices[0], err is None))

    result = run_loop(
        [_req(i) for i in range(4)],
        operation=None,  # type: ignore[arg-type]
        on_error="continue",
        send_one=_ok,
        audit_attempt=audit,
        to_envelope=_to_envelope,
        workers=1,
    )
    assert result.attempted == 4
    assert result.successes == 4
    # workers=1 preserves input order exactly (byte-for-byte sequential).
    assert [a[0] for a in audited] == [0, 1, 2, 3]
    assert [a.request.record_indices[0] for a in result.attempts] == [0, 1, 2, 3]


def test_run_loop_concurrent_continue_attempts_every_record() -> None:
    audited: list[tuple[int, bool]] = []
    lock = threading.Lock()

    def audit(req: ResolvedRequest, _resp: dict | None, err: Exception | None) -> None:
        with lock:
            audited.append((req.record_indices[0], err is None))

    def mixed(_op: object, request: ResolvedRequest) -> dict[str, object]:
        idx = request.record_indices[0]
        if idx in (3, 7):
            raise _SimulatedFailure(
                ErrorEnvelope(
                    error="bad",
                    type=ErrorType.VALIDATION,
                    status_code=400,
                    record_index=idx,
                    operation_id="x_create",
                )
            )
        return {"id": idx}

    result = run_loop(
        [_req(i) for i in range(10)],
        operation=None,  # type: ignore[arg-type]
        on_error="continue",
        send_one=mixed,
        audit_attempt=audit,
        to_envelope=_to_envelope,
        workers=4,
    )
    assert result.attempted == 10
    assert result.successes == 8
    # Order is not guaranteed under concurrency; compare as sets.
    assert {f.record_index for f in result.failures} == {3, 7}
    assert {a[0] for a in audited} == set(range(10))


def test_run_loop_concurrent_is_faster_than_sequential() -> None:
    def slow(_op: object, _request: ResolvedRequest) -> dict[str, object]:
        time.sleep(0.05)
        return {"id": 1}

    requests = [_req(i) for i in range(8)]

    start = time.monotonic()
    run_loop(
        requests,
        operation=None,  # type: ignore[arg-type]
        on_error="continue",
        send_one=slow,
        audit_attempt=lambda *_a: None,
        to_envelope=_to_envelope,
        workers=8,
    )
    concurrent_elapsed = time.monotonic() - start

    # 8 records * 50ms sequential = 400ms; with 8 workers it should be ~50ms.
    assert concurrent_elapsed < 0.20


def test_run_loop_concurrent_stop_halts_submission_after_failure() -> None:
    sent: list[int] = []
    lock = threading.Lock()

    def send(_op: object, request: ResolvedRequest) -> dict[str, object]:
        idx = request.record_indices[0]
        with lock:
            sent.append(idx)
        if idx == 0:
            raise _SimulatedFailure(
                ErrorEnvelope(
                    error="bad",
                    type=ErrorType.VALIDATION,
                    status_code=400,
                    record_index=0,
                    operation_id="x_create",
                )
            )
        time.sleep(0.02)
        return {"id": idx}

    result = run_loop(
        [_req(i) for i in range(100)],
        operation=None,  # type: ignore[arg-type]
        on_error="stop",
        send_one=send,
        audit_attempt=lambda *_a: None,
        to_envelope=_to_envelope,
        workers=2,
    )
    # On stop, the first failure halts new submission; in-flight tasks finish.
    # We must not have dispatched all 100 records.
    assert len(sent) < 100
    assert any(f.record_index == 0 for f in result.failures)
    assert result.attempted == len(result.attempts)


def test_loop_attempt_records_carry_response_or_envelope() -> None:
    result = run_loop(
        [_req(0), _req(1)],
        operation=None,  # type: ignore[arg-type]
        on_error="continue",
        send_one=_fail_at(1),
        audit_attempt=lambda *_a: None,
        to_envelope=_to_envelope,
    )
    assert isinstance(result.attempts[0], LoopAttempt)
    assert result.attempts[0].response == {"id": 1}
    assert result.attempts[0].failure is None
    assert result.attempts[1].response is None
    assert result.attempts[1].failure is not None
    assert result.attempts[1].failure.type is ErrorType.VALIDATION
