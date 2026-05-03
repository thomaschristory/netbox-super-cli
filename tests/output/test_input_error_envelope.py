"""Phase 4d: input_error envelope shape and exit-code mapping."""

from __future__ import annotations

from nsc.output.errors import (
    EXIT_CODES,
    ErrorEnvelope,
    ErrorType,
    input_error_envelope,
)


def test_input_error_type_value_is_spec_mandated() -> None:
    assert ErrorType.INPUT_ERROR.value == "input_error"


def test_input_error_exit_code_is_4() -> None:
    # Spec §4.4: "Envelope type input_error (exit 4)". Shares with VALIDATION.
    assert EXIT_CODES[ErrorType.INPUT_ERROR] == 4


def test_input_error_envelope_carries_bad_lines() -> None:
    bad_lines = [
        {"line": 2, "reason": "Expecting property name enclosed in double quotes"},
        {"line": 5, "reason": "Extra data"},
    ]
    env = input_error_envelope(
        message="3 of 10 NDJSON lines failed to parse",
        bad_lines=bad_lines,
        operation_id="dcim_devices_create",
    )
    assert isinstance(env, ErrorEnvelope)
    assert env.type is ErrorType.INPUT_ERROR
    assert env.error == "3 of 10 NDJSON lines failed to parse"
    assert env.operation_id == "dcim_devices_create"
    assert env.details == {"bad_lines": bad_lines}


def test_input_error_envelope_with_no_operation_id() -> None:
    env = input_error_envelope(
        message="parse error",
        bad_lines=[{"line": 1, "reason": "boom"}],
        operation_id=None,
    )
    assert env.operation_id is None
    assert env.details["bad_lines"] == [{"line": 1, "reason": "boom"}]
