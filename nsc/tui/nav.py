"""Shared screen-stack navigation helpers.

Textual keeps a blank default screen at ``screen_stack[0]``; the app's first
pushed screen sits at ``[1]``. "Going back" should only pop when a real screen
exists beneath the current one — otherwise we would reveal the blank base and
the terminal appears to go black.
"""

from __future__ import annotations

from typing import Any

from textual.app import App

_BASE_PLUS_ROOT = 2


def can_go_back(app: App[Any]) -> bool:
    """True when popping the current screen reveals a real screen, not the base."""
    return len(app.screen_stack) > _BASE_PLUS_ROOT
