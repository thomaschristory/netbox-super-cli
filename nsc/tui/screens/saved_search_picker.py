"""Modal screens for saving and loading local filter sets ("saved searches").

`SavedSearchNamePrompt` collects a name for the current filter state; it
dismisses with the typed string (blank means "no-op", handled by the caller).
`SavedSearchPicker` lists existing saved-search names and dismisses with the
chosen one (or None on cancel).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView

_PROMPT_HINT = "Enter save · Esc cancel"
_PICKER_HINT = "Enter load · d delete · Esc cancel"


@dataclass(frozen=True)
class SavedSearchChoice:
    """A picker outcome: load or delete the named saved search."""

    action: Literal["load", "delete"]
    name: str


class SavedSearchNamePrompt(ModalScreen[str]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="saved-name-box"):
            yield Label("Save search as", classes="filter-heading")
            yield Input(placeholder="name…", id="saved-name")
            yield Label(_PROMPT_HINT, id="saved-name-hint")

    def on_mount(self) -> None:
        self.query_one("#saved-name", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss("")


class SavedSearchPicker(ModalScreen["SavedSearchChoice | None"]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "cancel", "Cancel"),
        ("d", "delete", "Delete"),
    ]

    def __init__(self, names: list[str]) -> None:
        super().__init__()
        self._names = names

    def compose(self) -> ComposeResult:
        with Vertical(id="saved-picker-box"):
            yield Label("Load saved search", classes="filter-heading")
            yield ListView(id="saved-picker-list")
            yield Label(_PICKER_HINT, id="saved-picker-hint")

    def on_mount(self) -> None:
        listing = self.query_one("#saved-picker-list", ListView)
        for name in self._names:
            item = ListItem(Label(name))
            item.data = name  # type: ignore[attr-defined]
            listing.append(item)
        if self._names:
            listing.index = 0
        listing.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        name = getattr(event.item, "data", None)
        if isinstance(name, str):
            self.dismiss(SavedSearchChoice("load", name))

    def action_delete(self) -> None:
        listing = self.query_one("#saved-picker-list", ListView)
        item = listing.highlighted_child
        name = getattr(item, "data", None)
        if isinstance(name, str):
            self.dismiss(SavedSearchChoice("delete", name))

    def action_cancel(self) -> None:
        self.dismiss(None)
