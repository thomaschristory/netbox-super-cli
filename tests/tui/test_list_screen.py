from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Input, Static

from nsc.http.errors import NetBoxAPIError
from nsc.model.command_model import (
    CommandModel,
    FieldShape,
    Operation,
    PrimitiveType,
    RequestBodyShape,
    Resource,
    Tag,
)
from nsc.tui.app import NscTuiApp
from nsc.tui.screens.bulk_edit_form import BulkEditForm
from nsc.tui.screens.columns import ColumnChooserScreen
from nsc.tui.screens.detail import DetailScreen
from nsc.tui.screens.edit_form import EditForm
from nsc.tui.screens.filter import FilterScreen
from nsc.tui.screens.list import ListScreen
from nsc.tui.widgets.diff import DiffModal


class _FakeClient:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.post_calls: list[dict[str, Any]] = []

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any:
        self.calls.append((path, params))
        yield from self._records

    def post(
        self,
        path: str,
        *,
        json: Any | None = None,
        operation_id: str | None = None,
        sensitive_paths: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        self.post_calls.append(
            {
                "path": path,
                "json": json,
                "operation_id": operation_id,
                "sensitive_paths": sensitive_paths,
            }
        )
        return {}


def _model() -> CommandModel:
    op = Operation(
        operation_id="devices_list",
        http_method="GET",
        path="/api/dcim/devices/",
        default_columns=["id", "name"],
    )
    tag = Tag(name="dcim", resources={"devices": Resource(name="devices", list_op=op)})
    return CommandModel(info_title="t", info_version="1", schema_hash="h", tags={"dcim": tag})


class _ListApp(App[None]):
    def __init__(self, client: _FakeClient, *, base_filters: dict[str, Any] | None = None) -> None:
        super().__init__()
        self._client = client
        self._base_filters = base_filters or {}

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        model = _model()
        op = model.tags["dcim"].resources["devices"].list_op
        assert op is not None
        await self.push_screen(
            ListScreen(model, self._client, "dcim", "devices", op, base_filters=self._base_filters)
        )


@pytest.mark.asyncio
async def test_list_screen_loads_rows_into_table() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}, {"id": 2, "name": "sw2"}])
    app = _ListApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        table = app.screen.query_one(DataTable)
        assert table.row_count == 2
        assert client.calls[0][0] == "/api/dcim/devices/"


@pytest.mark.asyncio
async def test_reload_clears_table_loading_after_load() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}])
    app = _ListApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        await screen._reload()
        table = screen.query_one("#rows", DataTable)
        assert table.loading is False
        assert table.row_count == 1


@pytest.mark.asyncio
async def test_reload_clears_table_loading_after_error() -> None:
    class _FlakyClient(_FakeClient):
        def paginate(
            self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
        ) -> Any:
            self.calls.append((path, params))
            raise NetBoxAPIError(status_code=500, url=path, body_snippet="boom", headers={})
            yield  # pragma: no cover

    client = _FlakyClient([{"id": 1, "name": "sw1"}])
    app = _ListApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        screen.notify = lambda msg, **kwargs: None  # type: ignore[method-assign]
        await screen._reload()
        table = screen.query_one("#rows", DataTable)
        assert table.loading is False


@pytest.mark.asyncio
async def test_filter_requeries_with_param() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}])
    app = _ListApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        screen.apply_filters({"name": "sw1"})
        await pilot.pause()
        await app.workers.wait_for_complete()
        last_params = client.calls[-1][1]
        assert last_params is not None
        assert ("name", "sw1") in last_params.items()


@pytest.mark.asyncio
async def test_slash_opens_filter_screen() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}])
    app = _ListApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        assert isinstance(app.screen, FilterScreen)


@pytest.mark.asyncio
async def test_table_is_focused_after_mount() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}])
    app = _ListApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.focused, DataTable)


@pytest.mark.asyncio
async def test_enter_on_focused_table_opens_detail() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}, {"id": 2, "name": "sw2"}])
    app = _ListApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        table = app.screen.query_one(DataTable)
        table.move_cursor(row=1)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, DetailScreen)
        assert app.screen._record == {"id": 2, "name": "sw2"}


@pytest.mark.asyncio
async def test_base_filters_merge_with_extra_filters() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}])
    app = _ListApp(client, base_filters={"device_id": "7"})
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        screen.apply_filters({"name": "sw1"})
        await pilot.pause()
        await app.workers.wait_for_complete()
        last_params = client.calls[-1][1]
        assert last_params is not None
        assert last_params.get("device_id") == "7"
        assert last_params.get("name") == "sw1"


@pytest.mark.asyncio
async def test_refilter_replaces_prior_extra_filters() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}])
    app = _ListApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        screen.apply_filters({"name": "sw1"})
        screen.apply_filters({"name": "sw2"})
        await pilot.pause()
        await app.workers.wait_for_complete()
        last_params = client.calls[-1][1]
        assert last_params is not None
        assert last_params.get("name") == "sw2"


@pytest.mark.asyncio
async def test_applying_filters_reloads_with_merged_params() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}])
    app = _ListApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        screen.apply_filters({"status": "active"})
        await pilot.pause()
        await app.workers.wait_for_complete()
        last_params = client.calls[-1][1]
        assert last_params is not None
        assert ("status", "active") in last_params.items()


@pytest.mark.asyncio
async def test_back_on_root_list_does_not_blank_out() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}])
    app = _ListApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        notes: list[str] = []
        screen.notify = lambda msg, **kwargs: notes.append(msg)  # type: ignore[method-assign]
        screen.action_go_back()
        await pilot.pause()
        assert app.screen is screen  # still on the list, not the blank base
        assert notes  # hinted how to quit / switch


@pytest.mark.asyncio
async def test_f_opens_chooser_applies_columns_and_persists() -> None:
    saved: list[tuple[str, str, list[str]]] = []
    client = _FakeClient([{"id": 1, "name": "sw1", "status": "active"}])
    app = NscTuiApp(
        _model(),
        client,
        initial_resource="devices",
        save_columns=lambda tag, res, cols: saved.append((tag, res, cols)),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        listscreen = app.screen
        assert isinstance(listscreen, ListScreen)
        await pilot.press("f")
        await pilot.pause()
        chooser = app.screen
        assert isinstance(chooser, ColumnChooserScreen)
        # default columns are ["id", "name"]; show "status" (items index 2) too
        chooser.query_one("#columns-list").index = 2
        chooser.action_toggle_column()
        chooser.action_apply()
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert app.screen is listscreen  # chooser dismissed
        table = listscreen.query_one("#rows", DataTable)
        # marker column + the three chosen columns
        assert len(table.columns) == 4
    assert saved == [("dcim", "devices", ["id", "name", "status"])]


@pytest.mark.asyncio
async def test_api_error_during_reload_notifies_and_keeps_rows() -> None:
    class _FlakyClient(_FakeClient):
        def paginate(
            self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
        ) -> Any:
            self.calls.append((path, params))
            if params:  # a filter was applied — simulate a 400 from NetBox
                raise NetBoxAPIError(
                    status_code=400,
                    url=path,
                    body_snippet='{"manufacturer": ["Select a valid choice."]}',
                    headers={},
                )
            yield from self._records

    client = _FlakyClient([{"id": 1, "name": "sw1"}])
    app = _ListApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        notes: list[str] = []
        screen.notify = lambda msg, **kwargs: notes.append(msg)  # type: ignore[method-assign]
        await app.workers.wait_for_complete()
        rows_before = screen.query_one(DataTable).row_count
        screen.apply_filters({"manufacturer": "Cisco"})  # would 400
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert app.screen is screen  # did not crash out of the screen
        assert screen.query_one(DataTable).row_count == rows_before  # prior rows preserved
        assert notes and "manufacturer" in notes[0]  # error surfaced as a notification


def _create_model(*, with_create: bool = True) -> CommandModel:
    list_op = Operation(
        operation_id="devices_list",
        http_method="GET",
        path="/api/dcim/devices/",
        default_columns=["id", "name"],
    )
    create_op = (
        Operation(
            operation_id="dcim_devices_create",
            http_method="POST",
            path="/api/dcim/devices/",
            request_body=RequestBodyShape(
                top_level="object",
                fields={
                    "name": FieldShape(primitive=PrimitiveType.STRING),
                    "auth_key": FieldShape(primitive=PrimitiveType.STRING),
                },
                sensitive_paths=("auth_key",),
            ),
        )
        if with_create
        else None
    )
    devices = Resource(name="devices", list_op=list_op, create_op=create_op)
    tag = Tag(name="dcim", resources={"devices": devices})
    return CommandModel(info_title="t", info_version="1", schema_hash="h", tags={"dcim": tag})


class _CreateApp(App[None]):
    def __init__(self, client: _FakeClient, *, with_create: bool = True) -> None:
        super().__init__()
        self._client = client
        self._with_create = with_create

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        model = _create_model(with_create=self._with_create)
        op = model.tags["dcim"].resources["devices"].list_op
        assert op is not None
        await self.push_screen(ListScreen(model, self._client, "dcim", "devices", op))


@pytest.mark.asyncio
async def test_create_record_pushes_edit_form_in_create_mode() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}])
    app = _CreateApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        screen.action_create_record()
        await pilot.pause()
        form = app.screen
        assert isinstance(form, EditForm)
        assert form._record == {}
        assert form._op.operation_id == "dcim_devices_create"


@pytest.mark.asyncio
async def test_create_key_pushes_edit_form() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}])
    app = _CreateApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, EditForm)


@pytest.mark.asyncio
async def test_create_no_op_is_safe_no_op() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}])
    app = _CreateApp(client, with_create=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        screen.action_create_record()
        await pilot.pause()
        assert isinstance(app.screen, ListScreen)


@pytest.mark.asyncio
async def test_create_confirm_calls_post_with_full_body() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}])
    app = _CreateApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        screen.action_create_record()
        await pilot.pause()
        form = app.screen
        assert isinstance(form, EditForm)
        form.query_one("#field-name", Input).value = "sw9"
        await pilot.pause()
        form.action_save()
        await pilot.pause()
        assert isinstance(app.screen, DiffModal)
        await pilot.press("y")
        await pilot.pause()
        assert len(client.post_calls) == 1
        call = client.post_calls[0]
        assert call["path"] == "/api/dcim/devices/"
        assert call["json"] == {"name": "sw9"}
        assert call["operation_id"] == "dcim_devices_create"
        assert call["sensitive_paths"] == ("auth_key",)


@pytest.mark.asyncio
async def test_create_success_reloads_list() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}])
    app = _CreateApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        await app.workers.wait_for_complete()
        load_count = len(client.calls)
        screen.action_create_record()
        await pilot.pause()
        form = app.screen
        assert isinstance(form, EditForm)
        form.query_one("#field-name", Input).value = "sw9"
        await pilot.pause()
        form.action_save()
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert isinstance(app.screen, ListScreen)
        assert len(client.calls) > load_count


def _marker_cell(table: DataTable[str], row: int) -> str:
    return str(table.get_row_at(row)[0])


@pytest.mark.asyncio
async def test_toggle_select_with_v_marks_and_unmarks_row() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}, {"id": 2, "name": "sw2"}])
    app = _ListApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        await app.workers.wait_for_complete()
        table = screen.query_one(DataTable)
        table.move_cursor(row=0)
        await pilot.press("v")
        await pilot.pause()
        assert screen.selection.ids() == (1,)
        assert _marker_cell(table, 0).strip() == "*"
        assert _marker_cell(table, 1).strip() == ""
        await pilot.press("v")
        await pilot.pause()
        assert screen.selection.ids() == ()
        assert _marker_cell(table, 0).strip() == ""


@pytest.mark.asyncio
async def test_toggle_select_with_space_marks_row() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}, {"id": 2, "name": "sw2"}])
    app = _ListApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        await app.workers.wait_for_complete()
        table = screen.query_one(DataTable)
        table.move_cursor(row=1)
        await pilot.press("space")
        await pilot.pause()
        assert screen.selection.ids() == (2,)
        assert _marker_cell(table, 1).strip() == "*"


@pytest.mark.asyncio
async def test_selection_preserves_insertion_order() -> None:
    client = _FakeClient([{"id": 10, "name": "sw1"}, {"id": 20, "name": "sw2"}, {"id": 30}])
    app = _ListApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        await app.workers.wait_for_complete()
        table = screen.query_one(DataTable)
        table.move_cursor(row=2)
        await pilot.press("v")
        await pilot.pause()
        table.move_cursor(row=0)
        await pilot.press("v")
        await pilot.pause()
        assert screen.selection.ids() == (30, 10)


@pytest.mark.asyncio
async def test_reload_preserves_present_ids_and_drops_stale() -> None:
    records = [{"id": 1, "name": "sw1"}, {"id": 2, "name": "sw2"}, {"id": 3, "name": "sw3"}]
    client = _FakeClient(records)
    app = _ListApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        await app.workers.wait_for_complete()
        table = screen.query_one(DataTable)
        table.move_cursor(row=0)
        await pilot.press("v")
        table.move_cursor(row=2)
        await pilot.press("v")
        await pilot.pause()
        assert screen.selection.ids() == (1, 3)
        client._records = [{"id": 1, "name": "sw1"}, {"id": 2, "name": "sw2"}]
        await screen._reload()
        await pilot.pause()
        assert screen.selection.ids() == (1,)
        assert _marker_cell(table, 0).strip() == "*"
        assert _marker_cell(table, 1).strip() == ""


@pytest.mark.asyncio
async def test_toggle_select_on_empty_table_is_safe_no_op() -> None:
    client = _FakeClient([])
    app = _ListApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        await pilot.press("v")
        await pilot.pause()
        assert screen.selection.ids() == ()
        assert isinstance(app.screen, ListScreen)


def _bulk_model(*, with_update: bool = True) -> CommandModel:
    list_op = Operation(
        operation_id="devices_list",
        http_method="GET",
        path="/api/dcim/devices/",
        default_columns=["id", "name"],
    )
    update_op = (
        Operation(
            operation_id="dcim_devices_partial_update",
            http_method="PATCH",
            path="/api/dcim/devices/{id}/",
            request_body=RequestBodyShape(
                top_level="object",
                fields={"name": FieldShape(primitive=PrimitiveType.STRING)},
            ),
        )
        if with_update
        else None
    )
    devices = Resource(name="devices", list_op=list_op, update_op=update_op)
    tag = Tag(name="dcim", resources={"devices": devices})
    return CommandModel(info_title="t", info_version="1", schema_hash="h", tags={"dcim": tag})


class _BulkApp(App[None]):
    def __init__(self, client: _FakeClient, *, with_update: bool = True) -> None:
        super().__init__()
        self._client = client
        self._with_update = with_update

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        model = _bulk_model(with_update=self._with_update)
        op = model.tags["dcim"].resources["devices"].list_op
        assert op is not None
        await self.push_screen(ListScreen(model, self._client, "dcim", "devices", op))


@pytest.mark.asyncio
async def test_bulk_edit_pushes_form_with_selected_records_in_selection_order() -> None:
    records = [{"id": 10, "name": "sw1"}, {"id": 20, "name": "sw2"}, {"id": 30, "name": "sw3"}]
    client = _FakeClient(records)
    app = _BulkApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        await app.workers.wait_for_complete()
        table = screen.query_one(DataTable)
        table.move_cursor(row=2)
        await pilot.press("v")
        table.move_cursor(row=0)
        await pilot.press("v")
        await pilot.pause()
        assert screen.selection.ids() == (30, 10)
        screen.action_bulk_edit()
        await pilot.pause()
        form = app.screen
        assert isinstance(form, BulkEditForm)
        assert form._selected == [
            {"id": 30, "name": "sw3"},
            {"id": 10, "name": "sw1"},
        ]


@pytest.mark.asyncio
async def test_bulk_edit_with_empty_selection_is_safe_no_op() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}])
    app = _BulkApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        screen.action_bulk_edit()
        await pilot.pause()
        assert isinstance(app.screen, ListScreen)


@pytest.mark.asyncio
async def test_bulk_edit_no_update_op_is_safe_no_op() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}])
    app = _BulkApp(client, with_update=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        await app.workers.wait_for_complete()
        table = screen.query_one(DataTable)
        table.move_cursor(row=0)
        await pilot.press("v")
        await pilot.pause()
        screen.action_bulk_edit()
        await pilot.pause()
        assert isinstance(app.screen, ListScreen)


@pytest.mark.asyncio
async def test_bulk_edit_key_pushes_form() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}])
    app = _BulkApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        await app.workers.wait_for_complete()
        table = screen.query_one(DataTable)
        table.move_cursor(row=0)
        await pilot.press("v")
        await pilot.pause()
        await pilot.press("B")
        await pilot.pause()
        assert isinstance(app.screen, BulkEditForm)


@pytest.mark.asyncio
async def test_bulk_edit_reloads_list_after_form_dismisses() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}, {"id": 2, "name": "sw2"}])
    app = _BulkApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        table = screen.query_one(DataTable)
        table.move_cursor(row=0)
        await pilot.press("v")
        await pilot.pause()
        await app.workers.wait_for_complete()
        load_count = len(client.calls)
        screen.action_bulk_edit()
        await pilot.pause()
        form = app.screen
        assert isinstance(form, BulkEditForm)
        form.dismiss()
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert isinstance(app.screen, ListScreen)
        assert len(client.calls) > load_count
