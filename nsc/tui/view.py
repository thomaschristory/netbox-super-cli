"""Pure helpers turning records + operation metadata into table columns/rows."""

from __future__ import annotations

from typing import Any

from nsc.model.command_model import Operation
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


def build_rows(records: list[dict[str, Any]], columns: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for record in records:
        flat = flatten(record, columns=columns)
        rows.append([_cell(flat.get(col)) for col in columns])
    return rows


def _cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
