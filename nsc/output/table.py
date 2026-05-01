"""Rich table output formatter."""

from __future__ import annotations

import sys
from typing import Any, TextIO

from rich.console import Console
from rich.table import Table

from nsc.output.flatten import flatten


def render(
    data: list[dict[str, Any]] | dict[str, Any],
    *,
    stream: TextIO = sys.stdout,
    columns: list[str] | None = None,
) -> None:
    records = [data] if isinstance(data, dict) else list(data)
    if not records:
        Console(file=stream, force_terminal=False).print("(no records)")
        return

    flat_records = [flatten(r, columns=columns) for r in records]
    fieldnames = columns if columns is not None else _gather_fieldnames(flat_records)

    table = Table(show_header=True, header_style="bold")
    for col in fieldnames:
        table.add_column(col)
    for r in flat_records:
        table.add_row(*[_format_cell(r.get(col, "")) for col in fieldnames])

    Console(file=stream, force_terminal=False).print(table)


def _gather_fieldnames(records: list[dict[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for r in records:
        for k in r:
            seen.setdefault(k, None)
    return list(seen.keys())


def _format_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
