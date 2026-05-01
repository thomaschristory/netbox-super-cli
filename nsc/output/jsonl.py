"""JSON Lines output formatter."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO


def render(
    data: list[dict[str, Any]] | dict[str, Any],
    *,
    stream: TextIO = sys.stdout,
) -> None:
    if isinstance(data, dict):
        stream.write(json.dumps(data))
        stream.write("\n")
        return
    for record in data:
        stream.write(json.dumps(record))
        stream.write("\n")
