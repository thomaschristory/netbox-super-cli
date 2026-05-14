"""Rich table output formatter."""

from __future__ import annotations

import sys
from typing import Any, TextIO

from rich.table import Table

from nsc.output._console import make_console
from nsc.output.flatten import flatten

_STATUS_COLORS: dict[str, str] = {
    "active": "green",
    "enabled": "green",
    "online": "green",
    "connected": "green",
    "planned": "yellow",
    "staged": "yellow",
    "decommissioning": "yellow",
    "failed": "red",
    "disabled": "red",
    "offline": "red",
    "error": "red",
    "true": "green",
    "false": "dim",
}


def render(
    data: list[dict[str, Any]] | dict[str, Any],
    *,
    stream: TextIO = sys.stdout,
    columns: list[str] | None = None,
    color: bool = False,
) -> None:
    records = [data] if isinstance(data, dict) else list(data)
    if not records:
        make_console(stream, color=color).print("(no records)")
        return

    flat_records = [flatten(r, columns=columns) for r in records]
    fieldnames = columns if columns is not None else _gather_fieldnames(flat_records)

    table = Table(show_header=True, header_style="bold")
    for col in fieldnames:
        table.add_column(col)
    for r in flat_records:
        table.add_row(*[_format_cell(r.get(col, ""), color=color) for col in fieldnames])

    make_console(stream, color=color).print(table)


def _gather_fieldnames(records: list[dict[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for r in records:
        for k in r:
            seen.setdefault(k, None)
    return list(seen.keys())


def _format_cell(value: Any, *, color: bool = False) -> str:
    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)

    if not color:
        return text

    if not text:
        return "[dim]-[/]"

    style = _STATUS_COLORS.get(text.lower())
    if style:
        return f"[{style}]{text}[/]"
    return text
