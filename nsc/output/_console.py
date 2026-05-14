"""Shared Rich Console factory used across all output formatters."""

from __future__ import annotations

from typing import TextIO

from rich.console import Console


def make_console(stream: TextIO, *, color: bool, soft_wrap: bool = False) -> Console:
    if color:
        return Console(file=stream, force_terminal=True, soft_wrap=soft_wrap)
    return Console(file=stream, no_color=True, highlight=False, soft_wrap=soft_wrap)
