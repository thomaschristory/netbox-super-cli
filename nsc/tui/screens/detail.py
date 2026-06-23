"""DetailScreen — flattened fields plus schema-derived relationship tabs."""

from __future__ import annotations

from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Tab, Tabs

from nsc.model.command_model import CommandModel, Resource
from nsc.output.flatten import flatten
from nsc.tui._bindings import textual_bindings
from nsc.tui.relations import RelatedView, related_views


class DetailScreen(Screen[None]):
    BINDINGS: ClassVar[list[BindingType]] = textual_bindings("detail")

    def __init__(
        self,
        model: CommandModel,
        client: Any,
        tag: str,
        resource_name: str,
        resource: Resource,
        record: dict[str, Any],
    ) -> None:
        super().__init__()
        self._model = model
        self._client = client
        self._tag = tag
        self._resource_name = resource_name
        self._resource = resource
        self._record = record
        self._relations: list[RelatedView] = related_views(model, resource_name)
        self.title = f"{resource_name} #{record.get('id', '?')}"

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="fields")
        tabs = [Tab(v.resource_name, id=f"rel-{i}") for i, v in enumerate(self._relations)]
        yield Tabs(*tabs)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#fields", DataTable)
        table.add_columns("field", "value")
        for key, value in flatten(self._record).items():
            table.add_row(key, "" if value is None else str(value))

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_drill_relation(self) -> None:
        if not self._relations:
            return
        tabs = self.query_one(Tabs)
        active = tabs.active
        if not active:
            return
        index = int(active.removeprefix("rel-"))
        view = self._relations[index]
        record_id = self._record.get("id")
        if record_id is None:
            return
        from nsc.tui.screens.list import ListScreen  # noqa: PLC0415

        self.app.push_screen(
            ListScreen(
                self._model,
                self._client,
                view.tag,
                view.resource_name,
                view.list_op,
                base_filters={view.filter_param: str(record_id)},
            )
        )

    def action_next_tab(self) -> None:
        self.query_one(Tabs).action_next_tab()

    def action_prev_tab(self) -> None:
        self.query_one(Tabs).action_previous_tab()
