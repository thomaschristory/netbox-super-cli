"""ErrorType, ErrorEnvelope, JSON round-trip (Phase 3a)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from nsc.model.command_model import HttpMethod
from nsc.output.errors import (
    EXIT_CODES,
    ErrorEnvelope,
    ErrorType,
    render_to_json,
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
