"""writes.confirmation — write-time refusal helpers (Phase 3b)."""

from __future__ import annotations

import pytest

from nsc.cli.writes.confirmation import (
    refuse_all_on_writes,
    refuse_delete_without_id,
    refuse_list_input_in_3b,
    refuse_unknown_format_for_writes,
)
from nsc.cli.writes.input import RawWriteInput
from nsc.output.errors import ClientError, ErrorType


def test_refuse_all_on_writes_returns_client_error() -> None:
    with pytest.raises(ClientError) as exc_info:
        refuse_all_on_writes(operation_id="dcim_devices_create")
    assert exc_info.value.envelope.type is ErrorType.CLIENT
    assert "--all" in exc_info.value.envelope.error.lower()


def test_refuse_delete_without_id_includes_op_id() -> None:
    with pytest.raises(ClientError) as exc_info:
        refuse_delete_without_id(operation_id="dcim_devices_destroy")
    assert "id" in exc_info.value.envelope.error.lower()
    assert exc_info.value.envelope.operation_id == "dcim_devices_destroy"


def test_refuse_list_input_in_3b_when_explicit_list() -> None:
    raw = RawWriteInput(
        records=[{"a": 1}, {"a": 2}],
        source="file",
        is_explicit_list=True,
    )
    with pytest.raises(ClientError) as exc_info:
        refuse_list_input_in_3b(raw, operation_id="dcim_devices_create")
    assert "3c" in exc_info.value.envelope.error.lower()
    assert "bulk" in exc_info.value.envelope.error.lower()


def test_refuse_list_input_in_3b_passes_for_single_record() -> None:
    raw = RawWriteInput(records=[{"a": 1}], source="file")
    refuse_list_input_in_3b(raw, operation_id="dcim_devices_create")  # no raise


def test_refuse_unknown_format_value() -> None:
    with pytest.raises(ClientError):
        refuse_unknown_format_for_writes("toml")


def test_refuse_unknown_format_passes_for_supported() -> None:
    refuse_unknown_format_for_writes("yaml")
    refuse_unknown_format_for_writes(None)


def test_refuse_unknown_format_is_case_insensitive() -> None:
    refuse_unknown_format_for_writes("YAML")
    refuse_unknown_format_for_writes("Json")
    refuse_unknown_format_for_writes("YML")
