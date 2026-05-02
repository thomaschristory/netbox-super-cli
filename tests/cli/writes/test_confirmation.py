"""writes.confirmation — write-time refusal helpers (Phase 3c)."""

from __future__ import annotations

import pytest

from nsc.cli.writes.bulk import UnsupportedBulkError
from nsc.cli.writes.confirmation import (
    refuse_all_on_writes,
    refuse_bulk_and_no_bulk_together,
    refuse_delete_without_id,
    refuse_unknown_format_for_writes,
    refuse_unknown_on_error,
    refuse_unsupported_bulk,
)
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


def test_refuse_bulk_and_no_bulk_together_raises_client_error() -> None:
    with pytest.raises(ClientError) as exc_info:
        refuse_bulk_and_no_bulk_together(
            bulk=True,
            no_bulk=True,
            operation_id="dcim_devices_create",
        )
    env = exc_info.value.envelope
    assert env.type is ErrorType.CLIENT
    assert env.operation_id == "dcim_devices_create"
    assert env.details["flag"] == "--bulk/--no-bulk"


def test_refuse_bulk_and_no_bulk_together_silent_when_only_one_set() -> None:
    refuse_bulk_and_no_bulk_together(bulk=True, no_bulk=False, operation_id="x")
    refuse_bulk_and_no_bulk_together(bulk=False, no_bulk=True, operation_id="x")
    refuse_bulk_and_no_bulk_together(bulk=False, no_bulk=False, operation_id="x")


def test_refuse_unsupported_bulk_wraps_routing_error() -> None:
    err = UnsupportedBulkError("--bulk not supported here")
    with pytest.raises(ClientError) as exc_info:
        refuse_unsupported_bulk(err, operation_id="dcim_devices_create")
    env = exc_info.value.envelope
    assert env.type is ErrorType.CLIENT
    assert env.operation_id == "dcim_devices_create"
    assert env.details["flag"] == "--bulk"


@pytest.mark.parametrize("value", ["abort", "skip", "STOP", ""])
def test_refuse_unknown_on_error_rejects_anything_outside_stop_continue(value: str) -> None:
    with pytest.raises(ClientError) as exc_info:
        refuse_unknown_on_error(value)
    assert exc_info.value.envelope.details["flag"] == "--on-error"


@pytest.mark.parametrize("value", ["stop", "continue"])
def test_refuse_unknown_on_error_silent_for_supported(value: str) -> None:
    refuse_unknown_on_error(value)
