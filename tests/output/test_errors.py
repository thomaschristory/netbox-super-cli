"""ErrorType, ErrorEnvelope, JSON round-trip (Phase 3a)."""

from __future__ import annotations

import io
import json

import pytest
from pydantic import ValidationError

from nsc.config.models import OutputFormat
from nsc.model.command_model import HttpMethod
from nsc.output.errors import (
    ERROR_TYPE_PRECEDENCE,
    EXIT_CODES,
    ErrorEnvelope,
    ErrorType,
    RenderTarget,
    render_to_json,
    render_to_rich_stderr,
    select_render_target,
    summary_envelope,
    worst_error_type,
)


def test_error_type_values_are_lowercase_strings() -> None:
    expected = {
        "auth",
        "not_found",
        "validation",
        "conflict",
        "rate_limited",
        "server",
        "transport",
        "schema",
        "config",
        "client",
        "internal",
        "ambiguous_alias",
        "unknown_alias",
    }
    assert {e.value for e in ErrorType} == expected


def test_exit_codes_match_spec_table() -> None:
    assert EXIT_CODES == {
        ErrorType.SCHEMA: 3,
        ErrorType.VALIDATION: 4,
        ErrorType.SERVER: 5,
        ErrorType.CLIENT: 6,
        ErrorType.TRANSPORT: 7,
        ErrorType.AUTH: 8,
        ErrorType.NOT_FOUND: 9,
        ErrorType.CONFLICT: 10,
        ErrorType.RATE_LIMITED: 11,
        ErrorType.CONFIG: 12,
        ErrorType.INTERNAL: 1,
        ErrorType.AMBIGUOUS_ALIAS: 13,
        ErrorType.UNKNOWN_ALIAS: 14,
    }


def test_envelope_minimal_serialization() -> None:
    env = ErrorEnvelope(
        error="missing token",
        type=ErrorType.AUTH,
    )
    text = render_to_json(env)
    parsed = json.loads(text)
    assert parsed["error"] == "missing token"
    assert parsed["type"] == "auth"
    assert parsed["endpoint"] is None
    assert parsed["method"] is None
    assert parsed["operation_id"] is None
    assert parsed["status_code"] is None
    assert parsed["attempt_n"] is None
    assert parsed["audit_log_path"] is None
    assert parsed["record_index"] is None
    assert parsed["details"] == {}


def test_envelope_full_serialization() -> None:
    env = ErrorEnvelope(
        error="NetBox API 401",
        type=ErrorType.AUTH,
        endpoint="https://nb.example/api/dcim/devices/",
        method=HttpMethod.GET,
        operation_id="dcim_devices_list",
        status_code=401,
        attempt_n=1,
        audit_log_path="/home/u/.nsc/logs/audit.jsonl",
        record_index=None,
        details={"reason": "expired"},
    )
    parsed = json.loads(render_to_json(env))
    assert parsed["method"] == "GET"
    assert parsed["status_code"] == 401
    assert parsed["details"] == {"reason": "expired"}


def test_envelope_is_frozen() -> None:
    env = ErrorEnvelope(error="x", type=ErrorType.CLIENT)
    with pytest.raises(ValidationError):
        env.error = "y"


def test_render_to_json_compact_one_line() -> None:
    env = ErrorEnvelope(error="x", type=ErrorType.CLIENT)
    text = render_to_json(env)
    assert "\n" not in text


def test_select_render_target_json_output_to_stdout() -> None:
    target = select_render_target(output_format=OutputFormat.JSON, stdout_is_tty=True)
    assert target is RenderTarget.JSON_STDOUT


def test_select_render_target_table_on_tty_to_rich_stderr() -> None:
    target = select_render_target(output_format=OutputFormat.TABLE, stdout_is_tty=True)
    assert target is RenderTarget.RICH_STDERR


def test_select_render_target_table_when_stdout_piped_falls_back_to_json_stdout() -> None:
    target = select_render_target(output_format=OutputFormat.TABLE, stdout_is_tty=False)
    assert target is RenderTarget.JSON_STDOUT


def test_select_render_target_csv_piped_emits_json_to_stderr() -> None:
    target = select_render_target(output_format=OutputFormat.CSV, stdout_is_tty=False)
    assert target is RenderTarget.JSON_STDERR


def test_render_to_rich_stderr_writes_panel_to_provided_stream() -> None:
    env = ErrorEnvelope(
        error="boom",
        type=ErrorType.SERVER,
        endpoint="https://nb/api/x/",
        method=HttpMethod.GET,
        status_code=503,
    )
    buf = io.StringIO()
    render_to_rich_stderr(env, stream=buf)
    out = buf.getvalue()
    assert "boom" in out
    assert "server" in out
    assert "503" in out


def test_error_type_precedence_is_complete_and_ordered() -> None:
    expected = [
        ErrorType.INTERNAL,
        ErrorType.TRANSPORT,
        ErrorType.SERVER,
        ErrorType.VALIDATION,
        ErrorType.CONFLICT,
        ErrorType.RATE_LIMITED,
        ErrorType.NOT_FOUND,
        ErrorType.AUTH,
        ErrorType.CLIENT,
        ErrorType.SCHEMA,
        ErrorType.CONFIG,
        ErrorType.AMBIGUOUS_ALIAS,
        ErrorType.UNKNOWN_ALIAS,
    ]
    assert expected == ERROR_TYPE_PRECEDENCE


def test_worst_error_type_picks_the_first_in_precedence_order() -> None:
    assert worst_error_type([ErrorType.AUTH, ErrorType.SERVER, ErrorType.VALIDATION]) is (
        ErrorType.SERVER
    )
    assert worst_error_type([ErrorType.NOT_FOUND]) is ErrorType.NOT_FOUND


def test_worst_error_type_raises_on_empty() -> None:
    with pytest.raises(ValueError):
        worst_error_type([])


def test_summary_envelope_stop_shape() -> None:
    failure = ErrorEnvelope(
        error="server returned 400",
        type=ErrorType.VALIDATION,
        status_code=400,
        record_index=2,
        operation_id="dcim_devices_create",
    )
    env = summary_envelope(
        attempted=3,
        failures=[failure],
        on_error="stop",
        operation_id="dcim_devices_create",
        total_records=5,
    )
    assert env.type is ErrorType.VALIDATION
    assert env.record_index == 2
    assert env.details["partial_progress"] == {
        "success": 2,
        "failed": 1,
        "remaining": 2,
    }
    assert env.details["on_error"] == "stop"


def test_summary_envelope_raises_on_empty_failures() -> None:
    with pytest.raises(ValueError, match=r"summary_envelope requires at least one failure"):
        summary_envelope(
            attempted=0,
            failures=[],
            on_error="stop",
            operation_id="x",
            total_records=5,
        )


def test_summary_envelope_continue_shape() -> None:
    f1 = ErrorEnvelope(
        error="server returned 400",
        type=ErrorType.VALIDATION,
        status_code=400,
        record_index=0,
        operation_id="x_create",
    )
    f3 = ErrorEnvelope(
        error="server returned 401",
        type=ErrorType.AUTH,
        status_code=401,
        record_index=2,
        operation_id="x_create",
    )
    env = summary_envelope(
        attempted=5,
        failures=[f1, f3],
        on_error="continue",
        operation_id="x_create",
        total_records=5,
    )
    assert env.type is ErrorType.VALIDATION  # validation > auth
    assert env.record_index is None  # multiple failure indices — not a single index
    assert env.details["partial_progress"] == {
        "success": 3,
        "failed": 2,
        "remaining": 0,
    }
    assert env.details["on_error"] == "continue"
    assert len(env.details["failures"]) == 2
    assert {f["record_index"] for f in env.details["failures"]} == {0, 2}
    assert all("type" in f and "status_code" in f for f in env.details["failures"])
