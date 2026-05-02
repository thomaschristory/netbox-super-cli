"""YAML output formatter."""

from __future__ import annotations

import sys
from typing import Any, TextIO

from ruamel.yaml import YAML


def _emitter() -> YAML:
    """A safe-mode emitter configured for stable, block-style output.

    ruamel.yaml's safe dumper preserves regular `dict` insertion order natively
    (Python 3.7+), so no explicit `sort_keys=False` toggle is needed — and
    `YAML.sort_keys` is not part of the public API anyway.
    """
    yaml = YAML(typ="safe", pure=True)
    yaml.default_flow_style = False
    return yaml


def render(
    data: list[dict[str, Any]] | dict[str, Any],
    *,
    stream: TextIO = sys.stdout,
) -> None:
    _emitter().dump(data, stream)
