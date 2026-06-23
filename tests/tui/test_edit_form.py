from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Input, Select, Static, Switch

from nsc.model.command_model import (
    CommandModel,
    FieldShape,
    Operation,
    PrimitiveType,
    RequestBodyShape,
    Resource,
    Tag,
)
from nsc.tui.forms import SET_NULL
from nsc.tui.screens.edit_form import EditForm
from nsc.tui.screens.record_picker import RecordPicker


class _SpyClient:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records
        self.patch_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []
        self.paginate_calls: list[tuple[str, dict[str, Any] | None]] = []

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any:
        self.paginate_calls.append((path, params))
        yield from self._records

    def patch(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.patch_calls.append((path, body))
        return {}

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.post_calls.append((path, body))
        return {}


def _model() -> CommandModel:
    update_op = Operation(
        operation_id="dcim_devices_partial_update",
        http_method="PATCH",
        path="/api/dcim/devices/{id}/",
        request_body=RequestBodyShape(
            top_level="object",
            fields={
                "status": FieldShape(primitive=PrimitiveType.STRING, enum=["active", "offline"]),
                "enabled": FieldShape(primitive=PrimitiveType.BOOLEAN),
                "weight": FieldShape(primitive=PrimitiveType.INTEGER, nullable=True),
                "name": FieldShape(primitive=PrimitiveType.STRING),
                "auth_key": FieldShape(primitive=PrimitiveType.STRING),
                "site": FieldShape(primitive=PrimitiveType.INTEGER),
            },
            sensitive_paths=("auth_key",),
        ),
    )
    devices = Resource(name="devices", update_op=update_op)
    sites_list = Operation(
        operation_id="dcim_sites_list",
        http_method="GET",
        path="/api/dcim/sites/",
    )
    sites = Resource(name="sites", list_op=sites_list)
    tag = Tag(name="dcim", resources={"devices": devices, "sites": sites})
    return CommandModel(info_title="t", info_version="1", schema_hash="h", tags={"dcim": tag})


def _record() -> dict[str, Any]:
    return {
        "id": 5,
        "status": "active",
        "enabled": True,
        "weight": 10,
        "name": "sw1",
        "auth_key": "secret",
        "site": {"id": 3, "display": "HQ"},
    }


class _EditApp(App[None]):
    def __init__(self, client: _SpyClient) -> None:
        super().__init__()
        self._client = client

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        model = _model()
        resource = model.tags["dcim"].resources["devices"]
        op = resource.update_op
        assert op is not None
        await self.push_screen(EditForm(model, self._client, "dcim", "devices", op, _record()))


def _screen(app: _EditApp) -> EditForm:
    screen = app.screen
    assert isinstance(screen, EditForm)
    return screen


@pytest.mark.asyncio
async def test_renders_widget_per_kind() -> None:
    client = _SpyClient([])
    app = _EditApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _screen(app)
        assert isinstance(screen.query_one("#field-status"), Select)
        assert isinstance(screen.query_one("#field-enabled"), Switch)
        assert isinstance(screen.query_one("#field-weight"), Input)
        assert isinstance(screen.query_one("#field-name"), Input)
        auth = screen.query_one("#field-auth_key", Input)
        assert auth.password is True


@pytest.mark.asyncio
async def test_initial_values_come_from_record() -> None:
    client = _SpyClient([])
    app = _EditApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _screen(app)
        assert screen.query_one("#field-status", Select).value == "active"
        assert screen.query_one("#field-enabled", Switch).value is True
        assert screen.query_one("#field-name", Input).value == "sw1"
        assert screen.query_one("#field-weight", Input).value == "10"


@pytest.mark.asyncio
async def test_nullable_field_has_set_null_control() -> None:
    client = _SpyClient([])
    app = _EditApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#setnull-weight")


@pytest.mark.asyncio
async def test_changing_a_widget_stages_only_no_network() -> None:
    client = _SpyClient([])
    app = _EditApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _screen(app)
        name = screen.query_one("#field-name", Input)
        name.focus()
        await pilot.pause()
        name.value = "sw2"
        await pilot.pause()
        assert screen.staged.get("name") == "sw2"
        assert client.patch_calls == []
        assert client.post_calls == []


@pytest.mark.asyncio
async def test_switch_change_stages_only() -> None:
    client = _SpyClient([])
    app = _EditApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _screen(app)
        switch = screen.query_one("#field-enabled", Switch)
        switch.value = False
        await pilot.pause()
        assert screen.staged.get("enabled") is False
        assert client.patch_calls == []


@pytest.mark.asyncio
async def test_set_null_stages_sentinel() -> None:
    client = _SpyClient([])
    app = _EditApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#setnull-weight", Button).press()
        await pilot.pause()
        assert screen.staged.get("weight") is SET_NULL
        assert client.patch_calls == []


@pytest.mark.asyncio
async def test_fk_control_opens_record_picker() -> None:
    client = _SpyClient([{"id": 3, "display": "HQ"}, {"id": 4, "display": "Branch"}])
    app = _EditApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#fk-site", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, RecordPicker)
