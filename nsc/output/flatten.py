"""Shared dotted-path flattener used by table and csv formatters."""

from __future__ import annotations

import json
from typing import Any


def flatten(record: dict[str, Any], *, columns: list[str] | None = None) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    _walk(record, "", flat)
    if columns is None:
        return flat
    return {col: flat.get(col, "") for col in columns}


def _walk(value: Any, prefix: str, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            child = f"{prefix}.{k}" if prefix else k
            _walk(v, child, out)
    elif isinstance(value, list):
        out[prefix] = json.dumps(value)
    else:
        out[prefix] = value
