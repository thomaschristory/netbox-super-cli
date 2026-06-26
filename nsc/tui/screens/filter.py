"""FilterScreen — a web-UI-like filter builder over a list operation.

Combines an auto-curated common form (enums as dropdowns, foreign keys as
record-picker buttons), a search box over the full param set, a raw
``key=value`` line, and removable active chips. All input paths write into one
``FilterState``; ``Apply`` returns its params.

Foreign-key fields apply as ``{name}_id=<id>`` — NetBox's ``name`` filters want
a slug while the ``_id`` variant always accepts the picked record's id.
"""

from __future__ import annotations

from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, Select

from nsc.model.command_model import CommandModel, Operation, Parameter
from nsc.tui.filters import FilterState, common_filters, parse_raw, searchable_filters
from nsc.tui.fk import resolve_fk_target

_ANY = "—any—"


class FilterScreen(ModalScreen[dict[str, str]]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
        # Down falls through to the next field from single-line inputs; lists and
        # selects consume it for their own navigation. Up stays on (shift+)tab.
        Binding("down", "app.focus_next", "Next field", show=False),
        # ctrl+s (not ctrl+a, which inputs capture as cursor-home) applies.
        Binding("ctrl+s", "apply", "Apply"),
        # ctrl+w saves the current state under a name; ctrl+o loads a saved one.
        # Both avoid the printable keys the input-heavy form consumes.
        Binding("ctrl+w", "save_search", "Save search"),
        Binding("ctrl+o", "load_search", "Load saved"),
    ]

    def __init__(
        self,
        model: CommandModel,
        client: Any,
        operation: Operation,
        current: dict[str, str],
        *,
        tag: str | None = None,
        resource: str | None = None,
    ) -> None:
        super().__init__()
        self._model = model
        self._client = client
        self._tag = tag
        self._resource = resource
        self._common = common_filters(operation)
        self._searchable = searchable_filters(operation)
        self._fk_names = {p.name for p in self._common if self._is_fk(p.name)}
        self._fk_display: dict[str, str] = {}
        self.state = FilterState.from_params(current)
        # Suppresses the Select.Changed / Input.Changed handlers while we
        # programmatically re-sync the common widgets from state, so a
        # state-driven refresh never round-trips back and re-mutates state.
        self._syncing = False

    def _is_fk(self, name: str) -> bool:
        return resolve_fk_target(name, None, self._model).kind == "picker"

    @staticmethod
    def _apply_key(name: str) -> str:
        return name if name.endswith("_id") else f"{name}_id"

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
                yield Button("Apply  ⌃s", id="apply", variant="primary")
                yield Button("Clear", id="clear")
            yield Label(
                "↓/Tab next · Enter pick · ⌃s apply · ⌃w save · ⌃o load · Esc cancel",
                id="filter-hint",
            )

    def on_mount(self) -> None:
        self._refresh_chips()

    def _label(self, name: str) -> str:
        return "search" if name == "q" else name

    def _common_field(self, param: Parameter) -> ComposeResult:
        if param.name in self._fk_names:
            with Horizontal(classes="filter-field"):
                yield Label(self._label(param.name), classes="filter-label")
                yield Button(self._fk_button_text(param.name), id=f"fk-{param.name}")
            return
        current = self.state.as_params().get(param.name, "")
        with Horizontal(classes="filter-field"):
            yield Label(self._label(param.name), classes="filter-label")
            if param.enum is not None:
                # An active value outside the schema enum (stale enum, or set via
                # the raw line / a lookup) is injected as an extra option so the
                # Select shows the real filter instead of lying with "--any--".
                choices = list(param.enum)
                if current and current not in choices:
                    choices.append(current)
                options = [(choice, choice) for choice in choices]
                value = current if current in choices else Select.NULL
                yield Select(
                    options, value=value, prompt=_ANY, id=f"f-{param.name}", allow_blank=True
                )
            else:
                yield Input(value=current, id=f"f-{param.name}")

    def _fk_button_text(self, name: str) -> str:
        key = self._apply_key(name)
        display = self._fk_display.get(key) or self.state.as_params().get(key, "")
        return f"{self._label(name)}: {display or _ANY}"

    @staticmethod
    def _field_name(ident: str | None) -> str | None:
        if ident is None or not ident.startswith("f-"):
            return None
        return ident.removeprefix("f-")

    def on_select_changed(self, event: Select.Changed) -> None:
        if self._syncing:
            return
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
        if self._syncing:
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
                item = ListItem(Label(param.name), classes="search-result")
                item.data = param.name  # type: ignore[attr-defined]
                results.append(item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        name = getattr(event.item, "data", None)
        if not isinstance(name, str):
            return
        if self._is_fk(name):
            self._open_fk_picker(name)
            return
        raw = self.query_one("#raw", Input)
        raw.value = f"{name}="
        raw.focus()

    def _open_fk_picker(self, name: str) -> None:
        target = resolve_fk_target(name, None, self._model)
        if target.list_op is None:
            return
        from nsc.tui.screens.record_picker import RecordPicker  # noqa: PLC0415

        def _stage(result: tuple[int, str] | None) -> None:
            if result is None:
                return
            record_id, display = result
            key = self._apply_key(name)
            self.state.set(key, str(record_id))
            self._fk_display[key] = display
            self._update_fk_button(name)
            self._refresh_chips()

        self.app.push_screen(RecordPicker(self._client, target.list_op, None), _stage)

    def _update_fk_button(self, name: str) -> None:
        for button in self.query(f"#fk-{name}").results(Button):
            button.label = self._fk_button_text(name)

    def _sync_common_fields(self) -> None:
        params = self.state.as_params()
        self._syncing = True
        try:
            for param in self._common:
                if param.name in self._fk_names:
                    self._update_fk_button(param.name)
                elif param.enum is not None:
                    current = params.get(param.name, "")
                    select = self.query_one(f"#f-{param.name}", Select)
                    select.value = current if current in param.enum else Select.NULL
                else:
                    self.query_one(f"#f-{param.name}", Input).value = params.get(param.name, "")
        finally:
            self._syncing = False

    def _refresh_chips(self) -> None:
        chips = self.query_one("#chips", Vertical)
        chips.remove_children()
        for key, value in self.state.as_params().items():
            shown = self._fk_display.get(key, value)
            row = Horizontal(
                Label(f"{key} = {shown}", classes="chip-label"),
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
        elif ident is not None and ident.startswith("fk-"):
            self._open_fk_picker(ident.removeprefix("fk-"))
        elif ident is not None and ident.startswith("rm-"):
            self.state.remove(ident.removeprefix("rm-"))
            self._sync_common_fields()
            self._refresh_chips()

    def action_apply(self) -> None:
        self.dismiss(self.state.as_params())

    def action_clear(self) -> None:
        self.state = FilterState()
        self._fk_display.clear()
        self._sync_common_fields()
        self._refresh_chips()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save_search(self) -> None:
        if self._tag is None or self._resource is None:
            return
        if not callable(getattr(self.app, "save_search", None)):
            return
        from nsc.config.saved_searches import (  # noqa: PLC0415
            InvalidSavedSearchName,
            validate_saved_search_name,
        )
        from nsc.tui.screens.saved_search_picker import SavedSearchNamePrompt  # noqa: PLC0415

        def _save(name: str | None) -> None:
            if not name or not name.strip():
                return
            cleaned = name.strip()
            try:
                validate_saved_search_name(cleaned)
            except InvalidSavedSearchName as exc:
                self.notify(str(exc), severity="error")
                return
            self.app.save_search(  # type: ignore[attr-defined]
                self._tag, self._resource, cleaned, self.state.as_params()
            )

        self.app.push_screen(SavedSearchNamePrompt(), _save)

    def action_load_search(self) -> None:
        if self._tag is None or self._resource is None:
            return
        reader = getattr(self.app, "saved_searches_for", None)
        if not callable(reader):
            return
        saved: dict[str, dict[str, str]] = reader(self._tag, self._resource)
        if not saved:
            self.notify("No saved searches for this resource yet.")
            return
        from nsc.tui.screens.saved_search_picker import (  # noqa: PLC0415
            SavedSearchChoice,
            SavedSearchPicker,
        )

        def _chosen(choice: SavedSearchChoice | None) -> None:
            if choice is None:
                return
            if choice.action == "delete":
                self._delete_saved(choice.name)
                return
            params = saved.get(choice.name)
            if params is None:
                return
            self.state = FilterState.from_params(params)
            self._fk_display.clear()
            self._sync_common_fields()
            self._refresh_chips()

        self.app.push_screen(SavedSearchPicker(sorted(saved)), _chosen)

    def _delete_saved(self, name: str) -> None:
        deleter = getattr(self.app, "delete_search", None)
        if not callable(deleter):
            return
        deleter(self._tag, self._resource, name)
        self.notify(f"Deleted saved search {name!r}.")
