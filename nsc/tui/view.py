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
