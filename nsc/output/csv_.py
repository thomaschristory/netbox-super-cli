"""CSV output formatter (with nested-field flattening)."""

from __future__ import annotations

import csv
import sys
from typing import Any, TextIO

from nsc.output.flatten import flatten


def render(
    data: list[dict[str, Any]] | dict[str, Any],
    *,
    stream: TextIO = sys.stdout,
    columns: list[str] | None = None,
) -> None:
    records = [data] if isinstance(data, dict) else list(data)
    if not records:
        return
    flat_records = [flatten(r, columns=columns) for r in records]
    fieldnames = columns if columns is not None else _gather_fieldnames(flat_records)
    writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in flat_records:
        writer.writerow({k: ("" if v is None else v) for k, v in row.items()})


def _gather_fieldnames(records: list[dict[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for r in records:
        for k in r:
            seen.setdefault(k, None)
    return list(seen.keys())
