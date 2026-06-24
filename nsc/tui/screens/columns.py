"""ColumnChooserScreen — toggle and reorder the visible columns of a list."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView

from nsc.tui.columns import ColumnSelection

_HINT = "space toggle · shift+↑/↓ reorder · ↑/↓ move · Enter apply · Esc cancel"


class ColumnChooserScreen(ModalScreen[list[str]]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("space", "toggle_column", "Toggle"),
        ("shift+up", "move_up", "Move up"),
        ("shift+down", "move_down", "Move down"),
        ("enter", "apply", "Apply"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, available: list[str], visible: list[str]) -> None:
        super().__init__()
        self.selection = ColumnSelection(available, visible)

    def compose(self) -> ComposeResult:
        with Vertical(id="columns-box"):
            yield Label("Columns", classes="filter-heading")
            yield ListView(id="columns-list")
            yield Label(_HINT, id="columns-hint")

    def on_mount(self) -> None:
        self._rebuild(0)

    def _rebuild(self, index: int) -> None:
        listing = self.query_one("#columns-list", ListView)
        listing.clear()
        for name in self.selection.items:
            mark = "x" if self.selection.is_visible(name) else " "
            listing.append(ListItem(Label(f"[{mark}] {name}")))
        if self.selection.items:
            listing.index = max(0, min(index, len(self.selection.items) - 1))

    @property
    def _index(self) -> int:
        return self.query_one("#columns-list", ListView).index or 0

    def action_toggle_column(self) -> None:
        index = self._index
        if self.selection.items:
            self.selection.toggle(self.selection.items[index])
            self._rebuild(index)

    def action_move_up(self) -> None:
        self._rebuild(self.selection.move_up(self._index))

    def action_move_down(self) -> None:
        self._rebuild(self.selection.move_down(self._index))

    def action_apply(self) -> None:
        visible = self.selection.visible_in_order()
        if visible:  # never apply an empty column set
            self.dismiss(visible)

    def action_cancel(self) -> None:
        self.dismiss(None)
