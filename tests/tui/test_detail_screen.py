from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static, Tab, Tabs

from nsc.model.command_model import (
    CommandModel,
    Operation,
    Parameter,
    ParameterLocation,
    Resource,
    Tag,
)
from nsc.tui.screens.detail import DetailScreen


class _FakeClient:
    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any:
        return iter([])


def _model() -> CommandModel:
    devices = Resource(
        name="devices",
        list_op=Operation(operation_id="d_list", http_method="GET", path="/api/dcim/devices/"),
        get_op=Operation(operation_id="d_get", http_method="GET", path="/api/dcim/devices/{id}/"),
    )
    interfaces = Resource(
        name="interfaces",
        list_op=Operation(
            operation_id="i_list",
            http_method="GET",
            path="/api/dcim/interfaces/",
            parameters=[Parameter(name="device_id", location=ParameterLocation.QUERY)],
        ),
    )
    tag = Tag(name="dcim", resources={"devices": devices, "interfaces": interfaces})
    return CommandModel(info_title="t", info_version="1", schema_hash="h", tags={"dcim": tag})


class _DetailApp(App[None]):
    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        model = _model()
        resource = model.tags["dcim"].resources["devices"]
        record = {"id": 7, "name": "sw1", "site": {"display": "HQ"}}
        await self.push_screen(
            DetailScreen(model, _FakeClient(), "dcim", "devices", resource, record)
        )


@pytest.mark.asyncio
async def test_detail_shows_fields_and_relationship_tab() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        fields = app.screen.query_one("#fields", DataTable)
        assert fields.row_count >= 2  # id, name, site.display at least
        tabs = app.screen.query_one(Tabs)
        labels = [str(t.label) for t in tabs.query(Tab)]
        assert any("interfaces" in label for label in labels)
