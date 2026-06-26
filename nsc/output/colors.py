"""Framework-free value object + helper for NetBox-native hex colors.

NetBox FK/choice objects (roles, tags, …) carry a sibling ``color`` field — a
6-hex string (no leading ``#``) the web UI uses to tint the badge. The table and
TUI formatters preserve it by emitting a :class:`ColoredValue` instead of a bare
display string. This module imports nothing from cli/http/rich so it stays usable
by any formatter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEX = re.compile(r"\A[0-9a-fA-F]{6}\Z")


@dataclass(frozen=True)
class ColoredValue:
    text: str
    color: str | None


def normalize_hex(raw: object) -> str | None:
    """Return a lowercased 6-hex color (no leading ``#``) or ``None``.

    Accepts an optional leading ``#``. Anything that is not a string of exactly
    six hex digits (after stripping one leading ``#``) — including ``None``,
    non-strings, empty strings, and wrong lengths — yields ``None``.
    """
    if not isinstance(raw, str):
        return None
    candidate = raw[1:] if raw.startswith("#") else raw
    if _HEX.match(candidate):
        return candidate.lower()
    return None
