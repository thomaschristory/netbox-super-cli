"""Message-only confirmation modal.

Pure presentation: it shows a caller-supplied message and never touches the
client. Confirm dismisses with ``True``, cancel with ``False``.
"""

from __future__ import annotations

from typing import ClassVar

from nsc.tui.widgets._modal import ConfirmModalBase


class ConfirmModal(ConfirmModalBase):
    _BODY_ID: ClassVar[str] = "confirm-body"

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def render_text(self) -> str:
        return f"{self.message}\n\n[dim]Enter/y confirm · Esc/n cancel[/dim]"
