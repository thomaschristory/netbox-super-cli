"""Write-time refusal helpers.

Each helper raises ClientError with a fully-shaped envelope. The CLI layer
catches ClientError, emits the envelope, and exits with EXIT_CODES[CLIENT].

Spec §4.7, §4.8.
"""

from __future__ import annotations

from nsc.cli.writes.bulk import UnsupportedBulkError
from nsc.output.errors import ClientError, client_envelope

_SUPPORTED_FORMATS = {"yaml", "yml", "json"}
_SUPPORTED_ON_ERROR = {"stop", "continue"}


def refuse_all_on_writes(*, operation_id: str) -> None:
    raise ClientError(
        client_envelope(
            "--all is not supported on write commands (it is list-only)",
            operation_id=operation_id,
            flag="--all",
        )
    )


def refuse_delete_without_id(*, operation_id: str) -> None:
    raise ClientError(
        client_envelope(
            "delete requires a positional id (e.g. `nsc <tag> <resource> delete <id> --apply`)",
            operation_id=operation_id,
            flag="<id>",
        )
    )


def refuse_unknown_format_for_writes(value: str | None) -> None:
    if value is None:
        return
    if value.lower() not in _SUPPORTED_FORMATS:
        raise ClientError(
            client_envelope(
                f"--format {value!r} is not supported; expected one of: yaml, yml, json",
                flag="--format",
                value=value,
            )
        )


def refuse_bulk_and_no_bulk_together(
    *,
    bulk: bool,
    no_bulk: bool,
    operation_id: str,
) -> None:
    if bulk and no_bulk:
        raise ClientError(
            client_envelope(
                "--bulk and --no-bulk are mutually exclusive",
                operation_id=operation_id,
                flag="--bulk/--no-bulk",
            )
        )


def refuse_unsupported_bulk(err: UnsupportedBulkError, *, operation_id: str) -> None:
    raise ClientError(
        client_envelope(
            str(err),
            operation_id=operation_id,
            flag="--bulk",
        )
    )


def refuse_unknown_on_error(value: str) -> None:
    if value in _SUPPORTED_ON_ERROR:
        return
    raise ClientError(
        client_envelope(
            f"--on-error {value!r} is not supported; expected one of: stop, continue",
            flag="--on-error",
            value=value,
        )
    )


__all__ = [
    "refuse_all_on_writes",
    "refuse_bulk_and_no_bulk_together",
    "refuse_delete_without_id",
    "refuse_unknown_format_for_writes",
    "refuse_unknown_on_error",
    "refuse_unsupported_bulk",
]
