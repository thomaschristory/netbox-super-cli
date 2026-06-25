from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Input, ListView, Static, Tab, Tabs

from nsc.http.errors import NetBoxAPIError
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
from nsc.tui.screens.list import ListScreen
from nsc.tui.screens.record_picker import RecordPicker
from nsc.tui.widgets.confirm import ConfirmModal
from nsc.tui.widgets.diff import DiffModal


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
                fields={
                    "name": FieldShape(primitive=PrimitiveType.STRING),
                    "site": FieldShape(primitive=PrimitiveType.INTEGER),
                    "auth_key": FieldShape(primitive=PrimitiveType.STRING),
                },
                sensitive_paths=("auth_key",),
            ),
        ),
        delete_op=Operation(
            operation_id="d_delete",
            http_method="DELETE",
            path="/api/dcim/devices/{id}/",
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
    sites = Resource(
        name="sites",
        list_op=Operation(operation_id="s_list", http_method="GET", path="/api/dcim/sites/"),
    )
    tag = Tag(
        name="dcim",
        resources={
            "devices": devices,
            "interfaces": interfaces,
            "device-bays": bays,
            "sites": sites,
        },
    )
    return CommandModel(info_title="t", info_version="1", schema_hash="h", tags={"dcim": tag})


class _SpyClient:
    def __init__(self, *, fail_on_write: bool = False) -> None:
        self.patch_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []
        self._fail_on_write = fail_on_write

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any:
        return iter([])

    def patch(
        self,
        path: str,
        *,
        json: Any | None = None,
        operation_id: str | None = None,
        sensitive_paths: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        self.patch_calls.append({"path": path, "json": json, "operation_id": operation_id})
        if self._fail_on_write:
            raise NetBoxAPIError(status_code=400, url=path, body_snippet="bad request", headers={})
        return {}

    def delete(self, path: str, *, operation_id: str | None = None, **kwargs: Any) -> Any:
        self.delete_calls.append({"path": path, "operation_id": operation_id})
        if self._fail_on_write:
            raise NetBoxAPIError(
                status_code=400, url=path, body_snippet="cannot delete", headers={}
            )
        return {}


def _record() -> dict[str, Any]:
    return {"id": 7, "name": "sw1", "site": {"id": 3, "display": "HQ"}}


class _DetailApp(App[None]):
    def __init__(self, *, fail_on_write: bool = False) -> None:
        super().__init__()
        self.client = _SpyClient(fail_on_write=fail_on_write)

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        model = _model()
        resource = model.tags["dcim"].resources["devices"]
        await self.push_screen(
            DetailScreen(model, self.client, "dcim", "devices", resource, _record())
        )


def _detail(app: _DetailApp) -> DetailScreen:
    screen = app.screen
    assert isinstance(screen, DetailScreen)
    return screen


@pytest.mark.asyncio
async def test_detail_shows_editable_and_readonly_fields_plus_relationship_tab() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        fields = app.screen.query_one("#fields", DataTable)
        assert fields.row_count >= 3  # name, site (editable) + id (read-only)
        tabs = app.screen.query_one(Tabs)
        labels = [str(t.label) for t in tabs.query(Tab)]
        assert any("interfaces" in label for label in labels)


@pytest.mark.asyncio
async def test_pressing_e_edits_current_field_inline_and_enter_stages() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _detail(app)
        screen._table.move_cursor(row=0)  # the "name" field
        await pilot.press("e")
        await pilot.pause()
        editor = screen.query_one("#editor", Input)
        editor.value = "sw1-renamed"
        await pilot.press("enter")
        await pilot.pause()
        assert screen.staged == {"name": "sw1-renamed"}
        # editor closes, no PATCH yet (save is separate)
        assert not screen.query("#editor")
        assert app.client.patch_calls == []


@pytest.mark.asyncio
async def test_pressing_enter_starts_editing_current_field() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _detail(app)
        screen._table.move_cursor(row=0)  # the "name" field
        screen._table.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert screen._editing == "name"
        assert screen.query("#editor")


@pytest.mark.asyncio
async def test_staged_sensitive_field_renders_masked_in_table() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _detail(app)
        screen.staged = {"auth_key": "topsecret"}
        screen._refresh_rows()
        await pilot.pause()
        table = screen._table
        auth_row = next(i for i, r in enumerate(screen._rows) if r.name == "auth_key")
        cell = table.get_cell_at(Coordinate(auth_row, 1))
        assert cell == "****"
        assert "topsecret" not in str(cell)


@pytest.mark.asyncio
async def test_save_all_previews_then_patches_once() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _detail(app)
        screen.staged = {"name": "sw1-renamed"}
        screen.action_save_all()
        await pilot.pause()
        assert isinstance(app.screen, DiffModal)
        await pilot.press("y")
        await pilot.pause()
        assert app.client.patch_calls == [
            {
                "path": "/api/dcim/devices/7/",
                "json": {"name": "sw1-renamed"},
                "operation_id": "d_update",
            }
        ]
        # staged cleared after save
        assert _detail(app).staged == {}


@pytest.mark.asyncio
async def test_detail_save_all_api_error_keeps_staged_and_screen() -> None:
    app = _DetailApp(fail_on_write=True)
    notifications: list[tuple[str, Any]] = []
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _detail(app)
        original_notify = screen.notify

        def _capture(message: str, *args: Any, **kwargs: Any) -> None:
            notifications.append((message, kwargs.get("severity")))
            original_notify(message, *args, **kwargs)

        screen.notify = _capture  # type: ignore[method-assign]
        screen.staged = {"name": "sw1-renamed"}
        screen.action_save_all()
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert len(app.client.patch_calls) == 1
        # On error the staged change is preserved and we stay on the detail screen.
        assert screen.staged == {"name": "sw1-renamed"}
        assert app.screen is screen
        assert any(sev == "error" for _, sev in notifications)


@pytest.mark.asyncio
async def test_save_all_with_no_changes_does_not_patch() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _detail(app)
        screen.action_save_all()
        await pilot.pause()
        assert app.client.patch_calls == []
        assert not isinstance(app.screen, DiffModal)


@pytest.mark.asyncio
async def test_editing_fk_field_opens_record_picker() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _detail(app)
        # row 1 is the "site" FK field
        screen._table.move_cursor(row=1)
        screen.action_edit_field()
        await pilot.pause()
        assert isinstance(app.screen, RecordPicker)


@pytest.mark.asyncio
async def test_editing_readonly_field_is_noop() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _detail(app)
        # the read-only "id" row sits after the editable fields
        screen._table.move_cursor(row=screen._table.row_count - 1)
        screen.action_edit_field()
        await pilot.pause()
        assert screen._editing is None
        assert not screen.query("#editor")


@pytest.mark.asyncio
async def test_back_with_staged_changes_prompts_discard() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _detail(app)
        screen.staged = {"name": "changed"}
        screen.action_go_back()
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)
        assert "Discard" in app.screen.message


@pytest.mark.asyncio
async def test_escape_while_editing_cancels_edit_without_leaving() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _detail(app)
        screen.action_edit_field()
        await pilot.pause()
        assert screen._editing is not None
        await pilot.press("escape")
        await pilot.pause()
        assert screen._editing is None
        assert app.screen is screen  # still on detail


@pytest.mark.asyncio
async def test_o_drills_into_related_list() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        assert isinstance(app.screen, ListScreen)
        assert app.screen._base_filters == {"device_id": "7"}


@pytest.mark.asyncio
async def test_drill_relation_action_pushes_prefiltered_list() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        _detail(app).action_drill_relation()
        await pilot.pause()
        assert isinstance(app.screen, ListScreen)
        assert app.screen._base_filters == {"device_id": "7"}


@pytest.mark.asyncio
async def test_tab_and_shift_tab_cycle_active_tab() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _detail(app)
        tabs = app.screen.query_one(Tabs)
        first = tabs.active
        screen.action_next_tab()
        await pilot.pause()
        second = tabs.active
        assert second != first
        screen.action_prev_tab()
        await pilot.pause()
        assert tabs.active == first


class _NoUpdateApp(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.client = _SpyClient()

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        model = _model()
        devices = model.tags["dcim"].resources["devices"]
        resource = devices.model_copy(update={"update_op": None})
        await self.push_screen(
            DetailScreen(model, self.client, "dcim", "devices", resource, _record())
        )


@pytest.mark.asyncio
async def test_edit_field_is_noop_without_update_op() -> None:
    app = _NoUpdateApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DetailScreen)
        screen._table.move_cursor(row=0)
        screen.action_edit_field()
        await pilot.pause()
        assert screen._editing is None
        assert not screen.query("#editor")


@pytest.mark.asyncio
async def test_action_delete_record_pushes_confirm_naming_record() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        _detail(app).action_delete_record()
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, ConfirmModal)
        assert "devices" in modal.message
        assert "7" in modal.message


@pytest.mark.asyncio
async def test_pressing_d_pushes_confirm() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)


@pytest.mark.asyncio
async def test_delete_confirm_calls_client_delete_and_pops() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert app.client.delete_calls == [
            {"path": "/api/dcim/devices/7/", "operation_id": "d_delete"}
        ]
        assert app.screen is not screen


@pytest.mark.asyncio
async def test_delete_cancel_calls_nothing() -> None:
    app = _DetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert app.client.delete_calls == []
        assert app.screen is screen


@pytest.mark.asyncio
async def test_delete_api_error_notifies_and_does_not_pop() -> None:
    app = _DetailApp(fail_on_write=True)
    notifications: list[tuple[str, Any]] = []
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DetailScreen)
        original_notify = screen.notify

        def _capture(message: str, *args: Any, **kwargs: Any) -> None:
            notifications.append((message, kwargs.get("severity")))
            original_notify(message, *args, **kwargs)

        screen.notify = _capture  # type: ignore[method-assign]
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert len(app.client.delete_calls) == 1
        # Failed delete: stay on the detail screen and surface the error.
        assert app.screen is screen
        assert any(sev == "error" for _, sev in notifications)


class _NoDeleteApp(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.client = _SpyClient()

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        model = _model()
        devices = model.tags["dcim"].resources["devices"]
        resource = devices.model_copy(update={"delete_op": None})
        await self.push_screen(
            DetailScreen(model, self.client, "dcim", "devices", resource, _record())
        )


@pytest.mark.asyncio
async def test_action_delete_record_is_noop_without_delete_op() -> None:
    app = _NoDeleteApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DetailScreen)
        screen.action_delete_record()
        await pilot.pause()
        assert app.screen is screen
        assert app.client.delete_calls == []


class _CountingClient(_SpyClient):
    def __init__(self) -> None:
        super().__init__()
        self.paginate_count = 0

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any:
        self.paginate_count += 1
        return iter([])


class _DeleteOverListApp(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.client = _CountingClient()

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        model = _model()
        resource = model.tags["dcim"].resources["devices"]
        assert resource.list_op is not None
        await self.push_screen(ListScreen(model, self.client, "dcim", "devices", resource.list_op))
        await self.push_screen(
            DetailScreen(model, self.client, "dcim", "devices", resource, _record())
        )


@pytest.mark.asyncio
async def test_delete_reloads_underlying_list() -> None:
    app = _DeleteOverListApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        before = app.client.paginate_count
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert isinstance(app.screen, ListScreen)
        assert app.client.paginate_count == before + 1


# ---- text-kind FK detection + chosen-name display (issue #97) ---------------


def _fk_model() -> CommandModel:
    update_op = Operation(
        operation_id="dcim_devices_partial_update",
        http_method="PATCH",
        path="/api/dcim/devices/{id}/",
        request_body=RequestBodyShape(
            top_level="object",
            fields={"role": FieldShape(primitive=PrimitiveType.UNKNOWN)},
        ),
    )
    devices = Resource(name="devices", update_op=update_op)
    roles = Resource(
        name="device-roles",
        list_op=Operation(
            operation_id="dcim_device_roles_list",
            http_method="GET",
            path="/api/dcim/device-roles/",
        ),
    )
    tag = Tag(name="dcim", resources={"devices": devices, "device-roles": roles})
    return CommandModel(info_title="t", info_version="1", schema_hash="h", tags={"dcim": tag})


class _FkPickClient(_SpyClient):
    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any:
        return iter([{"id": 9, "display": "Leaf Switch"}])


class _FkDetailApp(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.client = _FkPickClient()

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        model = _fk_model()
        resource = model.tags["dcim"].resources["devices"]
        record = {
            "id": 7,
            "role": {
                "id": 2,
                "url": "https://nb/api/dcim/device-roles/2/",
                "display": "Top of Rack Switch",
            },
        }
        await self.push_screen(
            DetailScreen(model, self.client, "dcim", "devices", resource, record)
        )


@pytest.mark.asyncio
async def test_text_kind_fk_opens_picker_and_shows_chosen_name() -> None:
    app = _FkDetailApp()
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _detail(app)
        screen._table.move_cursor(row=0)  # the "role" FK field
        screen.action_edit_field()
        await pilot.pause()
        # UNKNOWN-primitive FK is detected from the nested value -> picker, not text input.
        picker = app.screen
        assert isinstance(picker, RecordPicker)
        picker.query_one(ListView).index = 0  # Leaf Switch -> id 9
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert screen.staged.get("role") == 9
        # The table renders the chosen name, not the bare id.
        rendered = [
            str(screen._table.get_cell_at(Coordinate(r, 1))) for r in range(screen._table.row_count)
        ]
        assert any("Leaf Switch" in cell for cell in rendered)
        # The save diff renders the name on both sides.
        screen.action_save_all()
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, DiffModal)
        rows = modal._rows
        role_row = next(r for r in rows if r.field == "role")
        assert role_row.old_display == "Top of Rack Switch"
        assert role_row.new_display == "Leaf Switch"
