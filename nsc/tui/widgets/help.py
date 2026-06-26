"""Full-screen help overlay generated from the keymap (cannot drift)."""

from __future__ import annotations

from typing import ClassVar

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from nsc.tui.keymap import help_groups

_TITLES = {
    "global": "Global",
    "list": "List view",
    "detail": "Detail view",
    "edit": "Edit form",
    "bulk": "Bulk edit form",
    "filter": "Filter builder",
}
_DISMISS_KEYS = {"escape", "q", "enter", "question_mark"}


def help_renderable() -> RenderableType:
    """A rich renderable of the keymap: a panel per context with a key/desc grid."""
    panels: list[RenderableType] = []
    for context, bindings in help_groups().items():
        if not bindings:
            continue
        grid = Table.grid(padding=(0, 3))
        grid.add_column(justify="right", style="bold cyan", no_wrap=True)
        grid.add_column(ratio=1)
        for binding in bindings:
            grid.add_row(binding.display_keys, binding.description)
        panels.append(
            Panel(
                grid,
                title=f"[b]{_TITLES[context]}[/b]",
                title_align="left",
                border_style="cyan",
                padding=(0, 1),
            )
        )
    title = Text("⌨  nsc — keyboard shortcuts", style="bold", justify="center")
    footer = Text("Press ?, Esc, q, or Enter to close", style="dim italic", justify="center")
    return Group(title, Text(), *panels, Text(), footer)


class HelpOverlay(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-body"):
            yield Static(help_renderable())

    def on_key(self, event: events.Key) -> None:
        # Dismiss only on explicit close keys so arrow/page keys can scroll the body.
        if event.key in _DISMISS_KEYS:
            event.stop()
            self.dismiss(None)
