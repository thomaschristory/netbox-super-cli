"""Shared dotted-path flattener used by table and csv formatters."""

from __future__ import annotations

import json
from typing import Any


def flatten(record: dict[str, Any], *, columns: list[str] | None = None) -> dict[str, Any]:
    if columns is None:
        flat: dict[str, Any] = {}
        _walk(record, "", flat)
        return flat
    return {col: _select(record, col) for col in columns}


def _walk(value: Any, prefix: str, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            child = f"{prefix}.{k}" if prefix else k
            _walk(v, child, out)
    elif isinstance(value, list):
        out[prefix] = json.dumps(value)
    else:
        out[prefix] = value


def _select(record: dict[str, Any], path: str) -> Any:
    cur: Any = record
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return ""
    return _displayify(cur)


def _displayify(value: Any) -> Any:
    if isinstance(value, dict):
        # FK objects carry `display`; choice fields carry `label` (status, etc.).
        for key in ("display", "label"):
            label = value.get(key)
            if isinstance(label, str):
                return label
        return json.dumps(value, separators=(",", ":"))
    if isinstance(value, list):
        return ", ".join(_as_cell(v) for v in value)
    return value


def _as_cell(value: Any) -> str:
    rendered = _displayify(value)
    return "" if rendered is None else str(rendered)
