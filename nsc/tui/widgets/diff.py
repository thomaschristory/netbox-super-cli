"""Confirm modal that presents staged changes as ``field: old -> new`` rows.

Pure presentation: it receives already-computed :class:`DiffRow` values (with
sensitive fields masked upstream by ``forms.diff_rows``) and never touches the
client. Confirm dismisses with ``True``, cancel with ``False``.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from nsc.tui.forms import DiffRow


class DiffModal(ModalScreen[bool]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("enter", "confirm", "Confirm"),
        ("y", "confirm", "Confirm"),
        ("escape", "cancel", "Cancel"),
        ("n", "cancel", "Cancel"),
    ]

    def __init__(self, rows: list[DiffRow]) -> None:
        super().__init__()
        self._rows = rows

    def render_text(self) -> str:
        lines: list[str] = ["[b]Review changes[/b]", ""]
        if not self._rows:
            lines.append("[dim]No changes.[/dim]")
        for row in self._rows:
            lines.append(f"  {row.field}: {row.old_display} -> {row.new_display}")
        lines.append("")
        lines.append("[dim]Enter/y confirm · Esc/n cancel[/dim]")
        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="diff-body"):
            yield Static(self.render_text(), markup=True)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
