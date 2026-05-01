"""JSON output formatter."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO


def render(
    data: list[dict[str, Any]] | dict[str, Any],
    *,
    stream: TextIO = sys.stdout,
    compact: bool = False,
) -> None:
    if compact:
        stream.write(json.dumps(data, separators=(",", ":")))
        stream.write("\n")
        return
    json.dump(data, stream, indent=2, sort_keys=False)
    stream.write("\n")
