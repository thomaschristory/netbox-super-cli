from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Select, Static, Switch

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
from nsc.tui.screens.bulk_edit_form import BulkEditForm


class _SpyClient:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records
        self.patch_calls: list[dict[str, Any]] = []
        self.post_calls: list[dict[str, Any]] = []
        self.paginate_calls: list[tuple[str, dict[str, Any] | None]] = []

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any:
        self.paginate_calls.append((path, params))
        yield from self._records

    def patch(
        self,
        path: str,
        *,
        json: Any | None = None,
        operation_id: str | None = None,
        sensitive_paths: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        self.patch_calls.append({"path": path, "json": json})
        return {}

    def post(
        self,
        path: str,
        *,
        json: Any | None = None,
        operation_id: str | None = None,
        sensitive_paths: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        self.post_calls.append({"path": path, "json": json})
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
            },
            sensitive_paths=("auth_key",),
        ),
    )
    devices = Resource(name="devices", update_op=update_op)
    tag = Tag(name="dcim", resources={"devices": devices})
    return CommandModel(info_title="t", info_version="1", schema_hash="h", tags={"dcim": tag})


def _selected() -> list[dict[str, Any]]:
    return [
        {"id": 1, "status": "active", "enabled": True, "weight": 10, "name": "sw1"},
        {"id": 2, "status": "active", "enabled": False, "weight": 20, "name": "sw2"},
    ]


def _update_op(model: CommandModel) -> Operation:
    op = model.tags["dcim"].resources["devices"].update_op
    assert op is not None
    return op


class _BulkApp(App[None]):
    def __init__(self, client: _SpyClient) -> None:
        super().__init__()
        self._client = client

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        model = _model()
        await self.push_screen(
            BulkEditForm(
                model,
                self._client,
                "dcim",
                "devices",
                _update_op(model),
                _selected(),
            )
        )


def _screen(app: _BulkApp) -> BulkEditForm:
    screen = app.screen
    assert isinstance(screen, BulkEditForm)
    return screen


@pytest.mark.asyncio
async def test_each_writable_field_renders_widget_and_include_toggle() -> None:
    client = _SpyClient([])
    app = _BulkApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        assert isinstance(screen.query_one("#field-status"), Select)
        assert isinstance(screen.query_one("#field-enabled"), Switch)
        assert isinstance(screen.query_one("#field-weight"), Input)
        assert isinstance(screen.query_one("#field-name"), Input)
        assert screen.query_one("#field-auth_key", Input).password is True
        for name in ("status", "enabled", "weight", "name", "auth_key"):
            include = screen.query_one(f"#include-{name}", Switch)
            assert include.value is False


@pytest.mark.asyncio
async def test_untouched_field_excluded_even_with_value() -> None:
    client = _SpyClient([])
    app = _BulkApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#field-status", Select).value = "offline"
        await pilot.pause()
        assert screen.bulk_set == {}
        assert client.patch_calls == []


@pytest.mark.asyncio
async def test_including_status_sets_bulk_set() -> None:
    client = _SpyClient([])
    app = _BulkApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#field-status", Select).value = "offline"
        await pilot.pause()
        screen.query_one("#include-status", Switch).value = True
        await pilot.pause()
        assert screen.bulk_set == {"status": "offline"}
        assert client.patch_calls == []


@pytest.mark.asyncio
async def test_excluding_after_including_removes_from_bulk_set() -> None:
    client = _SpyClient([])
    app = _BulkApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#field-status", Select).value = "offline"
        await pilot.pause()
        screen.query_one("#include-status", Switch).value = True
        await pilot.pause()
        assert "status" in screen.bulk_set
        screen.query_one("#include-status", Switch).value = False
        await pilot.pause()
        assert "status" not in screen.bulk_set


@pytest.mark.asyncio
async def test_set_null_for_nullable_field_lands_as_set_null() -> None:
    client = _SpyClient([])
    app = _BulkApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#include-weight", Switch).value = True
        await pilot.pause()
        screen.query_one("#setnull-weight").press()
        await pilot.pause()
        assert screen.bulk_set.get("weight") is SET_NULL
        assert client.patch_calls == []


@pytest.mark.asyncio
async def test_widget_change_only_no_network() -> None:
    client = _SpyClient([])
    app = _BulkApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#include-name", Switch).value = True
        await pilot.pause()
        name = screen.query_one("#field-name", Input)
        name.value = "renamed"
        await pilot.pause()
        assert screen.bulk_set.get("name") == "renamed"
        assert client.patch_calls == []
        assert client.post_calls == []
        assert client.paginate_calls == []


@pytest.mark.asyncio
async def test_preview_action_builds_changes_and_pushes_screen() -> None:
    client = _SpyClient([])
    app = _BulkApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#field-status", Select).value = "offline"
        await pilot.pause()
        screen.query_one("#include-status", Switch).value = True
        await pilot.pause()
        screen.action_preview()
        await pilot.pause()
        assert app.screen is not screen
        assert client.patch_calls == []
