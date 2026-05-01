"""YAML output formatter."""

from __future__ import annotations

import sys
from typing import Any, TextIO

import yaml


def render(
    data: list[dict[str, Any]] | dict[str, Any],
    *,
    stream: TextIO = sys.stdout,
) -> None:
    yaml.safe_dump(data, stream, default_flow_style=False, sort_keys=False)
