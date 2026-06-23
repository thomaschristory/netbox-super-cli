from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static, Tab, Tabs

from nsc.model.command_model import (
    CommandModel,
    FieldShape,
    Operation,
    Parameter,
    ParameterLocation,
    PrimitiveType,
    RequestBodyShape,
    Resource,
    Tag,
)
from nsc.tui.screens.detail import DetailScreen
from nsc.tui.screens.edit_form import EditForm
from nsc.tui.screens.list import ListScreen


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
        update_op=Operation(
            operation_id="d_update",
            http_method="PATCH",
            path="/api/dcim/devices/{id}/",
            request_body=RequestBodyShape(
                top_level="object",
                fields={"name": FieldShape(primitive=PrimitiveType.STRING)},
            ),
        ),
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
    bays = Resource(
        name="device-bays",
        list_op=Operation(
            operation_id="b_list",
            http_method="GET",
            path="/api/dcim/device-bays/",
            parameters=[Parameter(name="device_id", location=ParameterLocation.QUERY)],
        ),
    )
    tag = Tag(
        name="dcim",
        resources={"devices": devices, "interfaces": interfaces, "device-bays": bays},
    )
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


@pytest.mark.asyncio
async def test_drill_relation_pushes_prefiltered_list() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DetailScreen)
        screen.action_drill_relation()
        await pilot.pause()
        pushed = app.screen
        assert isinstance(pushed, ListScreen)
        assert pushed._base_filters == {"device_id": "7"}


@pytest.mark.asyncio
async def test_enter_drills_into_related_list() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ListScreen)
        assert app.screen._base_filters == {"device_id": "7"}


@pytest.mark.asyncio
async def test_tab_and_shift_tab_cycle_active_tab() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        tabs = app.screen.query_one(Tabs)
        first = tabs.active
        await pilot.press("tab")
        await pilot.pause()
        second = tabs.active
        assert second != first
        await pilot.press("shift+tab")
        await pilot.pause()
        assert tabs.active == first


@pytest.mark.asyncio
async def test_action_edit_record_pushes_edit_form() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DetailScreen)
        screen.action_edit_record()
        await pilot.pause()
        pushed = app.screen
        assert isinstance(pushed, EditForm)
        assert pushed._op.operation_id == "d_update"
        assert pushed._record == {"id": 7, "name": "sw1", "site": {"display": "HQ"}}


@pytest.mark.asyncio
async def test_pressing_e_pushes_edit_form() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, EditForm)


class _NoUpdateApp(App[None]):
    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        model = _model()
        devices = model.tags["dcim"].resources["devices"]
        resource = devices.model_copy(update={"update_op": None})
        record = {"id": 7, "name": "sw1"}
        await self.push_screen(
            DetailScreen(model, _FakeClient(), "dcim", "devices", resource, record)
        )


@pytest.mark.asyncio
async def test_action_edit_record_is_noop_without_update_op() -> None:
    app = _NoUpdateApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DetailScreen)
        screen.action_edit_record()
        await pilot.pause()
        assert app.screen is screen
