"""ListScreen — paginated, filterable table of one resource's records."""

from __future__ import annotations

from typing import Any, ClassVar, Protocol

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input

from nsc.model.command_model import CommandModel, Operation
from nsc.tui._bindings import textual_bindings
from nsc.tui.view import build_rows, choose_columns


class _Client(Protocol):
    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any: ...

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...


def _parse_filter(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in text.split():
        if "=" in token:
            key, _, value = token.partition("=")
            out[key.strip()] = value.strip()
    return out


class ListScreen(Screen[None]):
    BINDINGS: ClassVar[list[BindingType]] = textual_bindings("list")

    def __init__(
        self,
        model: CommandModel,
        client: _Client,
        tag: str,
        resource_name: str,
        operation: Operation,
        *,
        base_filters: dict[str, str] | None = None,
        columns_config: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._model = model
        self._client = client
        self._tag = tag
        self._resource_name = resource_name
        self._op = operation
        self._base_filters = dict(base_filters or {})
        self._extra_filters: dict[str, str] = {}
        self._columns_config = columns_config
        self._records: list[dict[str, Any]] = []
        self._columns: list[str] = []
        self.title = f"{tag} / {resource_name}"

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="filter: key=value …", id="filter")
        yield DataTable(id="rows")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#rows", DataTable).cursor_type = "row"
        self.reload()

    def _params(self) -> dict[str, str]:
        return {**self._base_filters, **self._extra_filters}

    def reload(self) -> None:
        records = list(self._client.paginate(self._op.path, self._params(), limit=200))
        table = self.query_one("#rows", DataTable)
        table.clear(columns=True)
        sample = records[0] if records else None
        columns = choose_columns(self._op, self._columns_config, sample)
        table.add_columns(*columns)
        for row in build_rows(records, columns):
            table.add_row(*row)
        self._records = records
        self._columns = columns

    def apply_filter(self, text: str) -> None:
        self._extra_filters = _parse_filter(text)
        self.reload()

    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.apply_filter(event.value)
        self.query_one("#rows", DataTable).focus()

    def action_refresh_list(self) -> None:
        self.reload()

    def action_cursor_down(self) -> None:
        self.query_one("#rows", DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#rows", DataTable).action_cursor_up()

    def action_cursor_top(self) -> None:
        self.query_one("#rows", DataTable).move_cursor(row=0)

    def action_cursor_bottom(self) -> None:
        table = self.query_one("#rows", DataTable)
        table.move_cursor(row=max(table.row_count - 1, 0))

    def action_open_detail(self) -> None:
        table = self.query_one("#rows", DataTable)
        if not self._records:
            return
        record = self._records[table.cursor_row]
        from nsc.tui.screens.detail import DetailScreen  # noqa: PLC0415

        resource = self._model.tags[self._tag].resources[self._resource_name]
        self.app.push_screen(
            DetailScreen(
                self._model, self._client, self._tag, self._resource_name, resource, record
            )
        )

    def action_go_back(self) -> None:
        self.app.pop_screen()
