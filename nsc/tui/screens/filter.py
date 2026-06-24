"""FilterScreen — a web-UI-like filter builder over a list operation.

Combines an auto-curated common form (enums as dropdowns), a search box over
the full param set, a raw ``key=value`` line, and removable active chips. All
three input paths write into one ``FilterState``; ``Apply`` returns its params.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, Select

from nsc.model.command_model import Operation, Parameter
from nsc.tui.filters import FilterState, common_filters, parse_raw, searchable_filters

_ANY = "—any—"


class FilterScreen(ModalScreen[dict[str, str]]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "apply", "Apply"),
    ]

    def __init__(self, operation: Operation, current: dict[str, str]) -> None:
        super().__init__()
        self._op = operation
        self._common = common_filters(operation)
        self._searchable = searchable_filters(operation)
        self.state = FilterState.from_params(current)

    def compose(self) -> ComposeResult:
        with Vertical(id="filter-body"):
            with VerticalScroll(id="filter-form"):
                yield Label("COMMON", classes="filter-heading")
                for param in self._common:
                    yield from self._common_field(param)
                yield Label("ADD FILTER", classes="filter-heading")
                yield Input(placeholder="search params…", id="search")
                yield ListView(id="search-results")
                yield Label("RAW", classes="filter-heading")
                yield Input(placeholder="key=value key2=value2", id="raw")
                yield Label("ACTIVE", classes="filter-heading")
                yield Vertical(id="chips")
            with Horizontal(id="filter-actions"):
                yield Button("Apply", id="apply", variant="primary")
                yield Button("Clear", id="clear")

    def on_mount(self) -> None:
        self._refresh_chips()

    def _label(self, name: str) -> str:
        return "search" if name == "q" else name

    def _common_field(self, param: Parameter) -> ComposeResult:
        current = self.state.as_params().get(param.name, "")
        with Horizontal(classes="filter-field"):
            yield Label(self._label(param.name), classes="filter-label")
            if param.enum is not None:
                options = [(choice, choice) for choice in param.enum]
                value = current if current in param.enum else Select.NULL
                yield Select(
                    options, value=value, prompt=_ANY, id=f"f-{param.name}", allow_blank=True
                )
            else:
                yield Input(value=current, id=f"f-{param.name}")

    @staticmethod
    def _field_name(ident: str | None) -> str | None:
        if ident is None or not ident.startswith("f-"):
            return None
        return ident.removeprefix("f-")

    def on_select_changed(self, event: Select.Changed) -> None:
        name = self._field_name(event.select.id)
        if name is None:
            return
        value = "" if event.value is Select.NULL else str(event.value)
        self.state.set(name, value)
        self._refresh_chips()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self._refresh_search(event.value)
            return
        name = self._field_name(event.input.id)
        if name is None:
            return
        self.state.set(name, event.value)
        self._refresh_chips()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "raw":
            self.state.merge(parse_raw(event.value))
            event.input.value = ""
            self._refresh_chips()

    def _refresh_search(self, query: str) -> None:
        needle = query.strip().lower()
        results = self.query_one("#search-results", ListView)
        results.clear()
        if not needle:
            return
        for param in self._searchable:
            if needle in param.name.lower():
                item = ListItem(Label(param.name))
                item.data = param.name  # type: ignore[attr-defined]
                results.append(item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        name = getattr(event.item, "data", None)
        if not isinstance(name, str):
            return
        raw = self.query_one("#raw", Input)
        raw.value = f"{name}="
        raw.focus()

    def _refresh_chips(self) -> None:
        chips = self.query_one("#chips", Vertical)
        chips.remove_children()
        for key, value in self.state.as_params().items():
            row = Horizontal(
                Label(f"{key} = {value}", classes="chip-label"),
                Button("x", id=f"rm-{key}", classes="chip-remove"),
                classes="chip",
            )
            chips.mount(row)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        ident = event.button.id
        if ident == "apply":
            self.action_apply()
        elif ident == "clear":
            self.action_clear()
        elif ident is not None and ident.startswith("rm-"):
            self.state.remove(ident.removeprefix("rm-"))
            self._refresh_chips()

    def action_apply(self) -> None:
        self.dismiss(self.state.as_params())

    def action_clear(self) -> None:
        self.state = FilterState()
        self._refresh_chips()

    def action_cancel(self) -> None:
        self.dismiss(None)
