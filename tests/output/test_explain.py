"""ExplainTrace and FieldDecision types (Phase 3a; logic in 3b)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from nsc.output.explain import (
    ExplainTrace,
    FieldDecision,
)


def test_field_decision_minimal() -> None:
    fd = FieldDecision(
        field_path="name",
        source="file",
        raw_value="rack-01",
        resolved_value="rack-01",
    )
    assert fd.field_path == "name"
    assert fd.source == "file"
    assert fd.note is None


def test_field_decision_source_must_be_known() -> None:
    with pytest.raises(ValidationError):
        FieldDecision(  # type: ignore[call-arg]
            field_path="x", source="bogus", raw_value=1, resolved_value=1
        )


def test_explain_trace_schema_version_default_is_1() -> None:
    trace = ExplainTrace(
        operation_id="dcim_devices_create",
        method_reasoning="POST because operationId says create",
        url_reasoning="No path templating",
    )
    assert trace.schema_version == 1
    assert trace.operation_summary is None
    assert trace.bulk_reasoning is None
    assert trace.decisions == []
    assert trace.decisions_truncated is False
    assert trace.requests == []


def test_explain_trace_full_round_trip() -> None:
    trace = ExplainTrace(
        operation_id="dcim_devices_create",
        operation_summary="Create a device",
        method_reasoning="POST",
        url_reasoning="No path templating",
        bulk_reasoning=None,
        decisions=[
            FieldDecision(
                field_path="name",
                source="file",
                raw_value="rack-01",
                resolved_value="rack-01",
            )
        ],
        decisions_truncated=False,
        requests=[],
    )
    parsed = json.loads(trace.model_dump_json())
    assert parsed["schema_version"] == 1
    assert parsed["operation_id"] == "dcim_devices_create"
    assert parsed["decisions"][0]["field_path"] == "name"


def test_explain_trace_is_frozen() -> None:
    trace = ExplainTrace(
        operation_id="x",
        method_reasoning="y",
        url_reasoning="z",
    )
    with pytest.raises(ValidationError):
        trace.operation_id = "y"  # type: ignore[misc]
