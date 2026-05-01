"""Single output entry point + format selection."""

from __future__ import annotations

import sys
from typing import Any, TextIO

from nsc.config.models import OutputFormat
from nsc.output import csv_, json_, jsonl, table, yaml_


def render(
    data: list[dict[str, Any]] | dict[str, Any],
    *,
    format: OutputFormat,
    columns: list[str] | None = None,
    stream: TextIO = sys.stdout,
    compact: bool = False,
) -> None:
    if format is OutputFormat.JSON:
        json_.render(data, stream=stream, compact=compact)
    elif format is OutputFormat.JSONL:
        jsonl.render(data, stream=stream)
    elif format is OutputFormat.YAML:
        yaml_.render(data, stream=stream)
    elif format is OutputFormat.CSV:
        csv_.render(data, stream=stream, columns=columns)
    elif format is OutputFormat.TABLE:
        table.render(data, stream=stream, columns=columns)
    else:  # pragma: no cover  (StrEnum exhaustively covered above)
        raise ValueError(f"unknown output format: {format!r}")


def select_format(
    *,
    cli_value: str | None,
    env_value: str | None,
    is_tty: bool,
    default: OutputFormat,
) -> OutputFormat:
    if cli_value is not None:
        return OutputFormat(cli_value)
    if env_value is not None:
        return OutputFormat(env_value)
    if not is_tty:
        return OutputFormat.JSON
    return default
