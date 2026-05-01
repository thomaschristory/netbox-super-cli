"""Write-time refusal helpers.

Each helper raises ClientError with a fully-shaped envelope. The CLI layer
catches ClientError, emits the envelope, and exits with EXIT_CODES[CLIENT].

Spec §4.7, §4.8.
"""

from __future__ import annotations

from nsc.cli.writes.input import RawWriteInput
from nsc.output.errors import ClientError, client_envelope

_SUPPORTED_FORMATS = {"yaml", "yml", "json"}


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


def refuse_list_input_in_3b(raw: RawWriteInput, *, operation_id: str) -> None:
    if not raw.is_explicit_list:
        return
    raise ClientError(
        client_envelope(
            "list-shaped -f input is supported in Phase 3c (bulk writes); "
            "this command currently accepts a single object only",
            operation_id=operation_id,
            flag="-f",
            value="list",
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


__all__ = [
    "refuse_all_on_writes",
    "refuse_delete_without_id",
    "refuse_list_input_in_3b",
    "refuse_unknown_format_for_writes",
]
