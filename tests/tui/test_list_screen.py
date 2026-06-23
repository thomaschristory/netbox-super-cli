from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static

from nsc.model.command_model import CommandModel, Operation, Resource, Tag
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
    def __init__(self, client: _FakeClient) -> None:
        super().__init__()
        self._client = client

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        model = _model()
        op = model.tags["dcim"].resources["devices"].list_op
        assert op is not None
        await self.push_screen(
            ListScreen(model, self._client, "dcim", "devices", op, base_filters={})
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
