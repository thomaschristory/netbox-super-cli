"""Shared Rich Console factory used across all output formatters."""

from __future__ import annotations

from typing import TextIO

from rich.console import Console


def make_console(stream: TextIO, *, color: bool) -> Console:
    if color:
        return Console(file=stream, force_terminal=True)
    return Console(file=stream, no_color=True, highlight=False)
