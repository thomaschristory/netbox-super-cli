from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Input, Static

from nsc.model.command_model import CommandModel, Operation, Resource, Tag
from nsc.tui.screens.detail import DetailScreen
from nsc.tui.screens.list import ListScreen


class _FakeClient:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any:
        self.calls.append((path, params))
        yield from self._records


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
        table = app.screen.query_one(DataTable)
        assert table.row_count == 2
        assert client.calls[0][0] == "/api/dcim/devices/"


@pytest.mark.asyncio
async def test_filter_requeries_with_param() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}])
    app = _ListApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        screen.apply_filter("name=sw1")
        await pilot.pause()
        last_params = client.calls[-1][1]
        assert last_params is not None
        assert ("name", "sw1") in last_params.items()


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
        screen.apply_filter("name=sw1")
        await pilot.pause()
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
        screen.apply_filter("name=sw1")
        screen.apply_filter("name=sw2")
        await pilot.pause()
        last_params = client.calls[-1][1]
        assert last_params is not None
        assert last_params.get("name") == "sw2"


@pytest.mark.asyncio
async def test_malformed_filter_token_is_dropped() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}])
    app = _ListApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        screen.apply_filter("bareword name=sw1")
        await pilot.pause()
        last_params = client.calls[-1][1]
        assert last_params is not None
        assert last_params == {"name": "sw1"}


@pytest.mark.asyncio
async def test_input_submitted_applies_filter_and_refocuses_table() -> None:
    client = _FakeClient([{"id": 1, "name": "sw1"}])
    app = _ListApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        screen.query_one("#filter", Input).focus()
        await pilot.pause()
        screen.query_one("#filter", Input).value = "name=sw1"
        await pilot.press("enter")
        await pilot.pause()
        last_params = client.calls[-1][1]
        assert last_params is not None
        assert ("name", "sw1") in last_params.items()
        assert isinstance(app.focused, DataTable)
