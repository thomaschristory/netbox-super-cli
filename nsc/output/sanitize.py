"""Make server-sourced text safe to put on a terminal.

Rich's `escape()` stops `[..]` markup, and Rich/Textual strip only BEL, BS, VT,
FF and CR. ESC, other C0/C1 controls and bidi overrides still reach the
terminal, so a NetBox object name could retitle or clear it, or spoof text
(issue #206).
"""

from __future__ import annotations

import unicodedata

from rich.markup import escape
from rich.text import Text


def printable(text: str) -> str:
    """Show control and format characters as visible `\\x..`/`\\u....` escapes."""
    return "".join(
        ch
        if ch in "\n\t" or not unicodedata.category(ch).startswith("C")
        else ch.encode("unicode_escape").decode("ascii")
        for ch in text
    )


def safe_markup(text: str) -> str:
    """`text` for interpolation into a Rich markup string."""
    return escape(printable(text))


def safe_text(text: str, style: str = "") -> Text:
    """A Rich `Text` (never parsed as markup) for widgets that would otherwise
    parse a plain `str` as markup, e.g. Textual's `DataTable` and `Label`."""
    return Text(printable(text), style=style)
