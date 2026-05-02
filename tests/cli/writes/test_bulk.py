"""Phase 3c — bulk capability detection and routing tests."""

from __future__ import annotations

from typing import Literal

import pytest

from nsc.cli.writes.bulk import BulkCapability, detect_bulk_capability
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
