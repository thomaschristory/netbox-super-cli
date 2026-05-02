"""Phase 3c — bulk capability detection and routing tests."""

from __future__ import annotations

from typing import Literal

import pytest

from nsc.cli.writes.bulk import (
    BulkCapability,
    RoutingMode,
    UnsupportedBulkError,
    detect_bulk_capability,
    route_to_bulk_or_loop,
)
from nsc.model.command_model import (
    HttpMethod,
    Operation,
    RequestBodyShape,
)


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
    with pytest.raises(ValueError):
        route_to_bulk_or_loop(
            record_count=0,
            capability=BulkCapability.BULK,
            bulk_flag=None,
        )
