"""Full-screen help overlay generated from the keymap (cannot drift)."""

from __future__ import annotations

from typing import ClassVar

from textual import events
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from nsc.tui.keymap import help_groups

_TITLES = {"global": "Global", "list": "List view", "detail": "Detail view"}
_DISMISS_KEYS = {"escape", "q", "enter", "question_mark"}


class HelpOverlay(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "dismiss", "Close")]

    def render_text(self) -> str:
        lines: list[str] = []
        for context, bindings in help_groups().items():
            lines.append(f"[b]{_TITLES[context]}[/b]")
            for b in bindings:
                lines.append(f"  {b.display_keys:<16} {b.description}")
            lines.append("")
        lines.append("[dim]Press Esc, q, or Enter to close[/dim]")
        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-body"):
            yield Static(self.render_text(), markup=True)

    def on_key(self, event: events.Key) -> None:
        # Dismiss only on explicit close keys so arrow/page keys can scroll the body.
        if event.key in _DISMISS_KEYS:
            event.stop()
            self.dismiss(None)
