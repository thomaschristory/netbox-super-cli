"""ListScreen — paginated, filterable table of one resource's records."""

from __future__ import annotations

import asyncio
from itertools import islice
from typing import Any, ClassVar, Protocol

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header

from nsc.http.errors import NetBoxAPIError, NetBoxClientError
from nsc.model.command_model import CommandModel, Operation
from nsc.tui._bindings import textual_bindings
from nsc.tui.errors import api_error_message
from nsc.tui.nav import can_go_back
from nsc.tui.selection import Selection
from nsc.tui.view import build_rows, choose_columns, count_label


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


CHUNK_SIZE = 100
# Every loaded row lives in a DataTable; past this the TUI gets sluggish and a
# filter is the better tool than scrolling.
MAX_LOADED_ROWS = 10_000


def _take(pager: Any, n: int) -> tuple[list[dict[str, Any]], Exception | None]:
    # Pulling one record at a time means a failed page fetch mid-chunk still
    # hands back what the pager already gave up; those records are gone from
    # its buffer and would otherwise be lost for good.
    records: list[dict[str, Any]] = []
    try:
        for record in islice(pager, n):
            records.append(record)
    except (NetBoxAPIError, NetBoxClientError) as exc:
        return records, exc
    return records, None


def _more_remaining(pager: Any, *, got: int, wanted: int) -> bool:
    if got < wanted:
        return False
    return getattr(pager, "has_more", True) is not False


_MARKER_HEADER = " "
_MARKER_ON = "*"
_MARKER_OFF = " "


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
        self._pager: Any = None
        self._has_more = False
        self._loading = False
        self._loading_more = False
        self.title = f"{tag} / {resource_name}"

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="rows")
        yield Footer()

    @property
    def selection(self) -> Selection:
        return self._selection

    @property
    def _table(self) -> DataTable[Any]:
        return self.query_one("#rows", DataTable)

    def on_mount(self) -> None:
        table = self._table
        table.cursor_type = "row"
        # Honour the user's saved column choice (persisted via the app) unless an
        # explicit columns_config was passed in.
        if self._columns_config is None:
            resolver = getattr(self.app, "columns_for", None)
            if callable(resolver):
                self._columns_config = resolver(self._tag, self._resource_name)
        self.reload()
        # Land on the table so vim/global keys fire; the filter is reachable via `/`.
        table.focus()

    def _params(self) -> dict[str, str]:
        return {**self._base_filters, **self._extra_filters}

    def reload(self) -> None:
        # Pass the bound coroutine *function* (not a coroutine object) so an exclusive
        # cancel before the worker starts never leaves a coroutine un-awaited.
        self._loading = True
        self.run_worker(self._reload, group="reload", exclusive=True)  # type: ignore[arg-type]

    async def _reload(self) -> None:
        # Clear `loading` only on our own success/error — never in a `finally`.
        # If this worker is cancelled (a newer exclusive reload superseded it),
        # that newer worker already set loading=True and owns turning it off;
        # clearing here would flicker the wheel off mid-load.
        table = self._table
        table.loading = True
        self._loading = True
        params = self._params()
        want = min(CHUNK_SIZE, MAX_LOADED_ROWS)

        def _first_chunk() -> tuple[Any, list[dict[str, Any]]]:
            pager = self._client.paginate(self._op.path, params)
            return pager, list(islice(pager, want))

        try:
            pager, records = await asyncio.to_thread(_first_chunk)
        except (NetBoxAPIError, NetBoxClientError) as exc:
            self.notify(api_error_message(exc), severity="error", timeout=8)
            table.loading = False
            self._loading = False
            return
        self._pager = pager
        self._has_more = _more_remaining(pager, got=len(records), wanted=want)
        self._populate(records, complete=not self._has_more)
        self._update_count()
        table.loading = False
        self._loading = False

    def action_load_more(self) -> None:
        if self._loading or self._loading_more or not self._has_more or self._pager is None:
            return
        if len(self._records) >= MAX_LOADED_ROWS:
            self.notify("Row cap reached — refine with a filter (/) to narrow the list.")
            return
        self._loading_more = True
        self.run_worker(self._load_more, group="load_more", exclusive=True)  # type: ignore[arg-type]

    async def _load_more(self) -> None:
        pager = self._pager
        want = min(CHUNK_SIZE, MAX_LOADED_ROWS - len(self._records))
        try:
            records, error = await asyncio.to_thread(_take, pager, want)
        finally:
            self._loading_more = False
        # A reload while this chunk was in flight replaced the pager; its rows
        # belong to a stale query and must not be appended.
        if pager is not self._pager:
            return
        self._append(records)
        if error is None:
            self._has_more = _more_remaining(pager, got=len(records), wanted=want)
        else:
            self._has_more = getattr(pager, "has_more", True) is not False
            self.notify(api_error_message(error), severity="error", timeout=8)
        if not self._has_more:
            self._prune_selection(self._records)
        self._update_count()

    def _append(self, records: list[dict[str, Any]]) -> None:
        table = self._table
        object_colors = bool(getattr(self.app, "object_colors", False))
        rows = build_rows(records, self._columns, object_colors=object_colors)
        for record, row in zip(records, rows, strict=True):
            table.add_row(self._marker_for(record.get("id")), *row)
        self._records.extend(records)

    def _update_count(self) -> None:
        total = getattr(self._pager, "total", None)
        loaded = len(self._records)
        self.sub_title = count_label(
            loaded,
            total if isinstance(total, int) else None,
            has_more=self._has_more,
            capped=self._has_more and loaded >= MAX_LOADED_ROWS,
        )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row >= self._table.row_count - 1:
            self.action_load_more()

    def _populate(self, records: list[dict[str, Any]], *, complete: bool) -> None:
        # Selected ids beyond a partial first chunk may still exist server-side;
        # only a fully loaded result set proves a selected id is gone.
        if complete:
            self._prune_selection(records)
        table = self._table
        table.clear(columns=True)
        sample = records[0] if records else None
        columns = choose_columns(self._op, self._columns_config, sample)
        labels = self._header_labels(columns)
        table.add_columns(_MARKER_HEADER, *(labels.get(c, c) for c in columns))
        object_colors = bool(getattr(self.app, "object_colors", False))
        rows = build_rows(records, columns, object_colors=object_colors)
        for record, row in zip(records, rows, strict=True):
            table.add_row(self._marker_for(record.get("id")), *row)
        self._records = records
        self._columns = columns

    def _header_labels(self, columns: list[str]) -> dict[str, str]:
        """Display labels for custom-field columns; raw key for everything else.

        Only resolves definitions when a ``custom_fields.<name>`` column is shown,
        so ordinary lists incur no extra request. The raw key stays the selector.
        """
        if not any(c.startswith("custom_fields.") for c in columns):
            return {}
        from nsc.savedfilters.custom_fields import custom_field_labels  # noqa: PLC0415

        defs_fn = getattr(self.app, "custom_field_defs_for", None)
        defs = defs_fn(self._tag, self._resource_name) if callable(defs_fn) else None
        return custom_field_labels(columns, defs)

    def _prune_selection(self, records: list[dict[str, Any]]) -> None:
        present = {record.get("id") for record in records}
        for record_id in self._selection.ids():
            if record_id not in present:
                self._selection.toggle(record_id)

    def _marker_for(self, record_id: Any) -> str:
        selected = record_id is not None and self._selection.contains(record_id)
        return _MARKER_ON if selected else _MARKER_OFF

    def action_open_filters(self) -> None:
        from nsc.tui.screens.filter import FilterScreen  # noqa: PLC0415

        def _apply(result: dict[str, str] | None) -> None:
            if result is not None:
                self.apply_filters(result)

        self.app.push_screen(
            FilterScreen(
                self._model,
                self._client,
                self._op,
                dict(self._extra_filters),
                tag=self._tag,
                resource=self._resource_name,
            ),
            _apply,
        )

    def apply_filters(self, params: dict[str, str]) -> None:
        self._extra_filters = dict(params)
        self.reload()

    def action_refresh_list(self) -> None:
        self.reload()

    def action_edit_columns(self) -> None:
        if not self._records:
            self.notify("No records loaded — nothing to choose columns from.")
            return
        from nsc.tui.columns import available_columns  # noqa: PLC0415
        from nsc.tui.screens.columns import ColumnChooserScreen  # noqa: PLC0415

        def _apply(columns: list[str] | None) -> None:
            if not columns:
                return
            self._columns_config = columns
            self.reload()
            saver = getattr(self.app, "save_columns", None)
            if callable(saver):
                saver(self._tag, self._resource_name, columns)

        available = available_columns(self._records)
        self.app.push_screen(
            ColumnChooserScreen(
                available,
                list(self._columns),
                labels=self._header_labels(available),
            ),
            _apply,
        )

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
        if can_go_back(self.app):
            self.app.pop_screen()
        else:
            self.notify("Nothing to go back to — press q to quit or ctrl+p to switch resource.")

    def _form_data_sources(self) -> tuple[dict[str, Any] | None, tuple[Any, ...] | None]:
        """Custom-field defs + available tags from the app, for editing widgets."""
        defs_fn = getattr(self.app, "custom_field_defs_for", None)
        tags_fn = getattr(self.app, "available_tags", None)
        defs = defs_fn(self._tag, self._resource_name) if callable(defs_fn) else None
        tags = tags_fn() if callable(tags_fn) else None
        return defs, tags

    def action_create_record(self) -> None:
        resource = self._model.tags[self._tag].resources[self._resource_name]
        create_op = resource.create_op
        if create_op is None:
            return
        from nsc.tui.screens.edit_form import EditForm  # noqa: PLC0415

        def _after(_: None) -> None:
            self.reload()

        defs, tags = self._form_data_sources()
        self.app.push_screen(
            EditForm(
                self._model,
                self._client,
                self._tag,
                self._resource_name,
                create_op,
                {},
                custom_field_defs=defs,
                available_tags=tags,
            ),
            _after,
        )

    def action_bulk_edit(self) -> None:
        resource = self._model.tags[self._tag].resources[self._resource_name]
        update_op = resource.update_op
        if update_op is None:
            return
        by_id = {r.get("id"): r for r in self._records}
        selected = [by_id[i] for i in self._selection.ids() if i in by_id]
        if not selected:
            return
        from nsc.tui.screens.bulk_edit_form import BulkEditForm  # noqa: PLC0415

        def _after(_: None) -> None:
            self._selection.clear()
            self.reload()

        defs, tags = self._form_data_sources()
        self.app.push_screen(
            BulkEditForm(
                self._model,
                self._client,
                self._tag,
                self._resource_name,
                update_op,
                selected,
                custom_field_defs=defs,
                available_tags=tags,
            ),
            _after,
        )
