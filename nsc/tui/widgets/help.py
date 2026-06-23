"""Full-screen help overlay generated from the keymap (cannot drift)."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from nsc.tui.keymap import help_groups

_TITLES = {"global": "Global", "list": "List view", "detail": "Detail view"}


def _help_text() -> str:
    lines: list[str] = []
    for context, bindings in help_groups().items():
        lines.append(f"[b]{_TITLES[context]}[/b]")
        for b in bindings:
            lines.append(f"  {b.display_keys:<16} {b.description}")
        lines.append("")
    lines.append("[dim]Press any key to close[/dim]")
    return "\n".join(lines)


class HelpOverlay(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "dismiss", "Close")]

    def render_text(self) -> str:
        return _help_text()

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-body"):
            yield Static(self.render_text(), markup=True)

    def on_key(self) -> None:
        self.dismiss(None)
