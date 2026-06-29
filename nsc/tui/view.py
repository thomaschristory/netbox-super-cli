"""Pure helpers turning records + operation metadata into table columns/rows."""

from __future__ import annotations

from typing import Any

from rich.text import Text

from nsc.model.command_model import Operation
from nsc.output.colors import ColoredValue
from nsc.output.flatten import flatten

_FALLBACK = ["id"]


def choose_columns(
    operation: Operation,
    configured: list[str] | None,
    sample: dict[str, Any] | None,
) -> list[str]:
    if configured:
        return list(configured)
    if operation.default_columns:
        return list(operation.default_columns)
    if sample:
        return list(sample.keys())
    return list(_FALLBACK)


def detail_path(list_path: str, record_id: object) -> str:
    """Build a single-record detail path from a list endpoint path and an id."""
    if "{id}" in list_path:
        return list_path.replace("{id}", str(record_id))
    base = list_path if list_path.endswith("/") else f"{list_path}/"
    return f"{base}{record_id}/"


def build_rows(
    records: list[dict[str, Any]],
    columns: list[str],
    *,
    object_colors: bool = False,
) -> list[list[str | Text]]:
    rows: list[list[str | Text]] = []
    for record in records:
        flat = flatten(record, columns=columns, with_colors=object_colors)
        rows.append([render_cell(flat.get(col)) for col in columns])
    return rows


def _colored_text(value: ColoredValue) -> Text:
    if value.color is None:
        return Text(value.text)
    return Text(value.text, style=f"#{value.color}")


def render_cell(value: Any) -> str | Text:
    """Render a flattened cell value as plain text or colored Rich ``Text``.

    Shared by the list table and the detail view so list-of-object fields (tags)
    render identically in both — colored chips or a comma-joined display string —
    rather than a raw repr.
    """
    if value is None:
        return ""
    if isinstance(value, ColoredValue):
        return _colored_text(value)
    if isinstance(value, list) and value and all(isinstance(v, ColoredValue) for v in value):
        out = Text()
        for i, item in enumerate(value):
            if i:
                out.append(", ")
            out.append_text(_colored_text(item))
        return out
    return str(value)
