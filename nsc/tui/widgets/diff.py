"""Confirm modal that presents staged changes as ``field: old -> new`` rows.

Pure presentation: it receives already-computed :class:`DiffRow` values (with
sensitive fields masked upstream by ``forms.diff_rows``) and never touches the
client. Confirm dismisses with ``True``, cancel with ``False``.
"""

from __future__ import annotations

from typing import ClassVar

from rich.markup import escape

from nsc.tui.forms import DiffRow
from nsc.tui.widgets._modal import ConfirmModalBase


class DiffModal(ConfirmModalBase):
    _BODY_ID: ClassVar[str] = "diff-body"

    def __init__(self, rows: list[DiffRow]) -> None:
        super().__init__()
        self._rows = rows

    def render_text(self) -> str:
        lines: list[str] = ["[b]Review changes[/b]", ""]
        if not self._rows:
            lines.append("[dim]No changes.[/dim]")
        for row in self._rows:
            field = escape(row.field)
            old = escape(row.old_display)
            new = escape(row.new_display)
            lines.append(f"  {field}: {old} -> {new}")
        lines.append("")
        lines.append("[dim]Enter/y confirm · Esc/n cancel[/dim]")
        return "\n".join(lines)
