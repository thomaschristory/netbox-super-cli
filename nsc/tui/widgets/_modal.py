"""Shared base for yes/no confirm modals.

Both the message and diff modals dismiss with ``True`` on confirm and ``False``
on cancel, bind the same keys, and render a single ``Static`` body. Subclasses
supply only ``render_text`` and the body container id.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static


class ConfirmModalBase(ModalScreen[bool]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("enter", "confirm", "Confirm"),
        ("y", "confirm", "Confirm"),
        ("escape", "cancel", "Cancel"),
        ("n", "cancel", "Cancel"),
    ]

    _BODY_ID: ClassVar[str]

    def render_text(self) -> str:
        raise NotImplementedError

    def compose(self) -> ComposeResult:
        with VerticalScroll(id=self._BODY_ID):
            yield Static(self.render_text(), markup=True)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
