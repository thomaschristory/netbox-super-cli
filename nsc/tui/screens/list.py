"""ListScreen — paginated, filterable table of one resource's records."""

from __future__ import annotations

from typing import Any, ClassVar, Protocol

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input

from nsc.model.command_model import CommandModel, Operation
from nsc.tui._bindings import textual_bindings
from nsc.tui.selection import Selection
from nsc.tui.view import build_rows, choose_columns


class _Client(Protocol):
    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any: ...

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...

    def patch(
        self,
        path: str,
        *,
        json: Any | None = None,
        operation_id: str | None = None,
        sensitive_paths: tuple[str, ...] = (),
    ) -> dict[str, Any]: ...

    def post(
        self,
        path: str,
        *,
        json: Any | None = None,
        operation_id: str | None = None,
        sensitive_paths: tuple[str, ...] = (),
    ) -> dict[str, Any]: ...


_MARKER_HEADER = " "
_MARKER_ON = "*"
_MARKER_OFF = " "


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
        self._selection: Selection = Selection()
        self.title = f"{tag} / {resource_name}"

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="filter: key=value …", id="filter")
        yield DataTable(id="rows")
        yield Footer()

    @property
    def selection(self) -> Selection:
        return self._selection

    @property
    def _table(self) -> DataTable[str]:
        return self.query_one("#rows", DataTable)

    def on_mount(self) -> None:
        table = self._table
        table.cursor_type = "row"
        self.reload()
        # Land on the table so vim/global keys fire; the filter is reachable via `/`.
        table.focus()

    def _params(self) -> dict[str, str]:
        return {**self._base_filters, **self._extra_filters}

    def reload(self) -> None:
        records = list(self._client.paginate(self._op.path, self._params(), limit=200))
        self._prune_selection(records)
        table = self._table
        table.clear(columns=True)
        sample = records[0] if records else None
        columns = choose_columns(self._op, self._columns_config, sample)
        table.add_columns(_MARKER_HEADER, *columns)
        for record, row in zip(records, build_rows(records, columns), strict=True):
            table.add_row(self._marker_for(record.get("id")), *row)
        self._records = records
        self._columns = columns

    def _prune_selection(self, records: list[dict[str, Any]]) -> None:
        present = {record.get("id") for record in records}
        for record_id in self._selection.ids():
            if record_id not in present:
                self._selection.toggle(record_id)

    def _marker_for(self, record_id: Any) -> str:
        selected = record_id is not None and self._selection.contains(record_id)
        return _MARKER_ON if selected else _MARKER_OFF

    def apply_filter(self, text: str) -> None:
        self._extra_filters = _parse_filter(text)
        self.reload()

    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.apply_filter(event.value)
        self._table.focus()

    def action_refresh_list(self) -> None:
        self.reload()

    def action_cursor_down(self) -> None:
        self._table.action_cursor_down()

    def action_cursor_up(self) -> None:
        self._table.action_cursor_up()

    def action_cursor_top(self) -> None:
        self._table.move_cursor(row=0)

    def action_cursor_bottom(self) -> None:
        table = self._table
        table.move_cursor(row=max(table.row_count - 1, 0))

    def action_toggle_select(self) -> None:
        table = self._table
        row = table.cursor_row
        if not self._records or not (0 <= row < len(self._records)):
            return
        record_id = self._records[row].get("id")
        if record_id is None:
            return
        self._selection.toggle(record_id)
        table.update_cell_at(Coordinate(row, 0), self._marker_for(record_id))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._open_detail(event.cursor_row)

    def action_open_detail(self) -> None:
        self._open_detail(self._table.cursor_row)

    def _open_detail(self, row: int) -> None:
        if not self._records or not (0 <= row < len(self._records)):
            return
        record = self._records[row]
        from nsc.tui.screens.detail import DetailScreen  # noqa: PLC0415

        resource = self._model.tags[self._tag].resources[self._resource_name]
        self.app.push_screen(
            DetailScreen(
                self._model, self._client, self._tag, self._resource_name, resource, record
            )
        )

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_create_record(self) -> None:
        resource = self._model.tags[self._tag].resources[self._resource_name]
        create_op = resource.create_op
        if create_op is None:
            return
        from nsc.tui.screens.edit_form import EditForm  # noqa: PLC0415

        def _after(_: None) -> None:
            self.reload()

        self.app.push_screen(
            EditForm(
                self._model,
                self._client,
                self._tag,
                self._resource_name,
                create_op,
                {},
            ),
            _after,
        )
