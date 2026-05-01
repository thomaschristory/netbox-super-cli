"""ExplainTrace.build_for + renderers (Phase 3b)."""

from __future__ import annotations

import io
import json

from nsc.cli.writes.apply import ResolvedRequest
from nsc.cli.writes.input import RawWriteInput
from nsc.cli.writes.preflight import Issue, PreflightResult
from nsc.model.command_model import (
    FieldShape,
    HttpMethod,
    Operation,
    PrimitiveType,
    RequestBodyShape,
)
from nsc.output.explain import ExplainTrace, render_to_json, render_to_rich_stdout


def _create_op() -> Operation:
    return Operation(
        operation_id="dcim_devices_create",
        http_method=HttpMethod.POST,
        path="/api/dcim/devices/",
        summary="Create a device",
        request_body=RequestBodyShape(
            top_level="object_or_array",
            required=["name"],
            fields={
                "name": FieldShape(primitive=PrimitiveType.STRING),
                "count": FieldShape(primitive=PrimitiveType.INTEGER),
            },
        ),
    )


def test_build_for_records_field_decisions_from_file() -> None:
    raw = RawWriteInput(records=[{"name": "rack-01"}], source="file")
    pre = PreflightResult(ok=True)
    req = ResolvedRequest(
        method=HttpMethod.POST,
        url="https://nb/api/dcim/devices/",
        body={"name": "rack-01"},
        operation_id="dcim_devices_create",
        record_indices=[0],
    )
    trace = ExplainTrace.build_for(_create_op(), raw, pre, [req], field_overrides=set())
    assert trace.operation_id == "dcim_devices_create"
    assert trace.operation_summary == "Create a device"
    assert any(d.field_path == "name" and d.source == "file" for d in trace.decisions)


def test_build_for_records_field_flag_overrides() -> None:
    raw = RawWriteInput(
        records=[{"name": "from-flag", "count": 2}],
        source="file_plus_fields",
    )
    pre = PreflightResult(ok=True)
    req = ResolvedRequest(
        method=HttpMethod.POST,
        url="https://nb/api/dcim/devices/",
        body={"name": "from-flag", "count": 2},
        operation_id="dcim_devices_create",
        record_indices=[0],
    )
    trace = ExplainTrace.build_for(_create_op(), raw, pre, [req], field_overrides={"name"})
    name_decision = next(d for d in trace.decisions if d.field_path == "name")
    assert name_decision.source == "field_flag"
    assert name_decision.note and "override" in name_decision.note.lower()


def test_build_for_records_schema_cast_when_string_to_int() -> None:
    # raw record had count="3" (string); ResolvedRequest body has count=3 (int)
    raw = RawWriteInput(records=[{"name": "x", "count": "3"}], source="fields_only")
    pre = PreflightResult(ok=True)
    req = ResolvedRequest(
        method=HttpMethod.POST,
        url="https://nb/api/dcim/devices/",
        body={"name": "x", "count": 3},
        operation_id="dcim_devices_create",
        record_indices=[0],
    )
    trace = ExplainTrace.build_for(_create_op(), raw, pre, [req], field_overrides={"name", "count"})
    count_decision = next(d for d in trace.decisions if d.field_path == "count")
    assert count_decision.raw_value == "3"
    assert count_decision.resolved_value == 3
    # source remains field_flag, but a schema_cast note is attached
    assert count_decision.note and "cast" in count_decision.note.lower()


def test_build_for_caps_decisions_at_200() -> None:
    fields = {f"f{i}": FieldShape(primitive=PrimitiveType.STRING) for i in range(250)}
    op = Operation(
        operation_id="big_create",
        http_method=HttpMethod.POST,
        path="/api/x/",
        request_body=RequestBodyShape(top_level="object", fields=fields),
    )
    record = {f"f{i}": "v" for i in range(250)}
    raw = RawWriteInput(records=[record], source="file")
    pre = PreflightResult(ok=True)
    req = ResolvedRequest(
        method=HttpMethod.POST,
        url="https://nb/api/x/",
        body=record,
        operation_id="big_create",
        record_indices=[0],
    )
    trace = ExplainTrace.build_for(op, raw, pre, [req], field_overrides=set())
    assert len(trace.decisions) == 200
    assert trace.decisions_truncated is True


def test_render_to_json_is_stable_one_line_round_trip() -> None:
    raw = RawWriteInput(records=[{"name": "x"}], source="file")
    pre = PreflightResult(ok=True)
    req = ResolvedRequest(
        method=HttpMethod.POST,
        url="https://nb/api/dcim/devices/",
        body={"name": "x"},
        operation_id="dcim_devices_create",
        record_indices=[0],
    )
    trace = ExplainTrace.build_for(_create_op(), raw, pre, [req], field_overrides=set())
    text = render_to_json(trace)
    parsed = json.loads(text)
    assert parsed["schema_version"] == 1
    assert parsed["operation_id"] == "dcim_devices_create"
    assert parsed["requests"][0]["method"] == "POST"


def test_render_to_rich_stdout_writes_a_panel() -> None:
    raw = RawWriteInput(records=[{"name": "x"}], source="file")
    pre = PreflightResult(ok=True)
    req = ResolvedRequest(
        method=HttpMethod.POST,
        url="https://nb/api/dcim/devices/",
        body={"name": "x"},
        operation_id="dcim_devices_create",
        record_indices=[0],
    )
    trace = ExplainTrace.build_for(_create_op(), raw, pre, [req], field_overrides=set())
    buf = io.StringIO()
    render_to_rich_stdout(trace, stream=buf)
    out = buf.getvalue()
    assert "dcim_devices_create" in out
    assert "POST" in out


def test_explain_trace_with_preflight_issues_renders_them() -> None:
    pre = PreflightResult(
        ok=False,
        issues=[
            Issue(
                record_index=0,
                field_path="name",
                kind="missing_required",
                message="required field 'name' is missing",
            )
        ],
    )
    raw = RawWriteInput(records=[{}], source="fields_only")
    req = ResolvedRequest(
        method=HttpMethod.POST,
        url="https://nb/api/dcim/devices/",
        body={},
        operation_id="dcim_devices_create",
        record_indices=[0],
    )
    trace = ExplainTrace.build_for(_create_op(), raw, pre, [req], field_overrides=set())
    text = render_to_json(trace)
    parsed = json.loads(text)
    assert parsed["preflight"]["ok"] is False
    assert parsed["preflight"]["issues"][0]["field_path"] == "name"
