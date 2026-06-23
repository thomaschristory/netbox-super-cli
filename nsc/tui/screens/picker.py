"""Fuzzy resource picker — landing screen and ``ctrl+p`` jump target."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView

from nsc.model.command_model import CommandModel
from nsc.tui.catalog import ResourceRef, filter_resources, list_resources


class ResourcePicker(ModalScreen[ResourceRef]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "dismiss", "Close")]

    def __init__(self, model: CommandModel) -> None:
        super().__init__()
        self._refs = list_resources(model)

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Input(placeholder="Filter resources…", id="picker-filter")
            yield ListView(id="picker-list")

    def on_mount(self) -> None:
        self._populate(self._refs)
        self.query_one("#picker-filter", Input).focus()

    def _populate(self, refs: list[ResourceRef]) -> None:
        lv = self.query_one("#picker-list", ListView)
        lv.clear()
        for ref in refs:
            item = ListItem(Label(ref.label))
            item.data = ref  # type: ignore[attr-defined]
            lv.append(item)
        if refs:
            lv.index = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        self._populate(filter_resources(self._refs, event.value))

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self._dismiss_with(self.query_one("#picker-list", ListView).highlighted_child)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self._dismiss_with(event.item)

    def _dismiss_with(self, item: ListItem | None) -> None:
        ref = getattr(item, "data", None)
        if isinstance(ref, ResourceRef):
            self.dismiss(ref)
