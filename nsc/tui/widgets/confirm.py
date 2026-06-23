"""Message-only confirmation modal.

Pure presentation: it shows a caller-supplied message and never touches the
client. Confirm dismisses with ``True``, cancel with ``False``.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static


class ConfirmModal(ModalScreen[bool]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("enter", "confirm", "Confirm"),
        ("y", "confirm", "Confirm"),
        ("escape", "cancel", "Cancel"),
        ("n", "cancel", "Cancel"),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def render_text(self) -> str:
        return f"{self.message}\n\n[dim]Enter/y confirm · Esc/n cancel[/dim]"

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="confirm-body"):
            yield Static(self.render_text(), markup=True)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
