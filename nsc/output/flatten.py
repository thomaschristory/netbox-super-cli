"""Shared dotted-path flattener used by table and csv formatters."""

from __future__ import annotations

import json
from typing import Any

from nsc.output.colors import ColoredValue, normalize_hex


def flatten(
    record: dict[str, Any],
    *,
    columns: list[str] | None = None,
    with_colors: bool = False,
) -> dict[str, Any]:
    if columns is None:
        flat: dict[str, Any] = {}
        _walk(record, "", flat)
        return flat
    return {col: _select(record, col, with_colors=with_colors) for col in columns}


def _walk(value: Any, prefix: str, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            child = f"{prefix}.{k}" if prefix else k
            _walk(v, child, out)
    elif isinstance(value, list):
        out[prefix] = json.dumps(value)
    else:
        out[prefix] = value


def _select(record: dict[str, Any], path: str, *, with_colors: bool = False) -> Any:
    cur: Any = record
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return ""
    return _displayify(cur, with_colors=with_colors)


def _displayify(value: Any, *, with_colors: bool = False) -> Any:
    if isinstance(value, dict):
        # FK objects carry `display`; choice fields carry `label` (status, etc.).
        for key in ("display", "label"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                if with_colors:
                    color = normalize_hex(value.get("color"))
                    if color is not None:
                        return ColoredValue(candidate, color)
                return candidate
        return json.dumps(value, separators=(",", ":"))
    if isinstance(value, list):
        cells = [_as_cell(v, with_colors=with_colors) for v in value]
        if with_colors and any(isinstance(c, ColoredValue) for c in cells):
            # Keep the list uniform so downstream formatters (which require a
            # homogeneous list of ColoredValue) don't reject a mix and emit a
            # raw repr. Promote plain strings to an uncolored ColoredValue.
            return [c if isinstance(c, ColoredValue) else ColoredValue(c, None) for c in cells]
        return ", ".join(c.text if isinstance(c, ColoredValue) else c for c in cells)
    return value


def _as_cell(value: Any, *, with_colors: bool = False) -> str | ColoredValue:
    rendered = _displayify(value, with_colors=with_colors)
    if isinstance(rendered, ColoredValue):
        return rendered
    return "" if rendered is None else str(rendered)
