"""Rich table output formatter."""

from __future__ import annotations

import sys
from typing import Any, TextIO

from rich.markup import escape
from rich.table import Table

from nsc.output._console import make_console
from nsc.output.colors import ColoredValue
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
    object_colors: bool = False,
) -> None:
    records = [data] if isinstance(data, dict) else list(data)
    if not records:
        make_console(stream, color=color).print("(no records)")
        return

    with_colors = color and object_colors
    flat_records = [flatten(r, columns=columns, with_colors=with_colors) for r in records]
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


def _colored_markup(value: ColoredValue) -> str:
    inner = escape(value.text)
    if value.color is None:
        return inner
    return f"[#{value.color}]{inner}[/]"


def _format_colored(value: ColoredValue | list[ColoredValue], *, color: bool) -> str:
    # Object colors only ever reach here when color is on (gated in render), but
    # escape unconditionally so a bare ColoredValue can't inject markup.
    if isinstance(value, ColoredValue):
        return _colored_markup(value) if color else escape(value.text)
    if not color:
        return escape(", ".join(v.text for v in value))
    return ", ".join(_colored_markup(v) for v in value)


def _is_colored_list(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    return all(isinstance(v, ColoredValue) for v in value)


def _format_cell(value: Any, *, color: bool = False) -> str:
    if isinstance(value, ColoredValue) or _is_colored_list(value):
        return _format_colored(value, color=color)

    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)

    # Rich parses markup in table cells regardless of the no-color setting, so
    # arbitrary cell values must be escaped on every return path.
    if not color:
        return escape(text)

    if not text:
        return "[dim]-[/]"

    style = _STATUS_COLORS.get(text.lower())
    if style:
        return f"[{style}]{escape(text)}[/]"
    return escape(text)
