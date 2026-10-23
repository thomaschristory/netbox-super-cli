"""Single output entry point + format selection."""

from __future__ import annotations

import sys
from typing import Any, TextIO

from nsc.config.models import OutputFormat
from nsc.output import csv_, json_, jsonl, table, yaml_


class InvalidOutputFormatError(ValueError):
    def __init__(self, value: str, *, source: str) -> None:
        valid = ", ".join(f.value for f in OutputFormat)
        super().__init__(
            f"invalid output format {value!r} (from {source}); expected one of: {valid}"
        )
        self.value = value
        self.source = source


def render(
    data: list[dict[str, Any]] | dict[str, Any],
    *,
    format: OutputFormat,
    columns: list[str] | None = None,
    header_labels: dict[str, str] | None = None,
    stream: TextIO = sys.stdout,
    compact: bool = False,
    color: bool = False,
    object_colors: bool = False,
) -> None:
    if format is OutputFormat.JSON:
        json_.render(data, stream=stream, compact=compact)
    elif format is OutputFormat.JSONL:
        jsonl.render(data, stream=stream)
    elif format is OutputFormat.YAML:
        yaml_.render(data, stream=stream)
    elif format is OutputFormat.CSV:
        csv_.render(data, stream=stream, columns=columns, header_labels=header_labels)
    elif format is OutputFormat.TABLE:
        table.render(
            data,
            stream=stream,
            columns=columns,
            color=color,
            object_colors=object_colors,
            header_labels=header_labels,
        )
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
        return _parse_format(cli_value, source="--output")
    if env_value is not None:
        return _parse_format(env_value, source="NSC_OUTPUT")
    if not is_tty:
        return OutputFormat.JSON
    return default


def _parse_format(value: str, *, source: str) -> OutputFormat:
    try:
        return OutputFormat(value)
    except ValueError:
        raise InvalidOutputFormatError(value, source=source) from None
