from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Input, ListView, Select, SelectionList, Static, Switch

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
from nsc.savedfilters.custom_fields import CustomFieldDef
from nsc.savedfilters.tags import TagDef
from nsc.tui.forms import SET_NULL, tags_payload
from nsc.tui.screens.bulk_edit_form import BulkEditForm
from nsc.tui.screens.list import ListScreen
from nsc.tui.screens.record_picker import RecordPicker
from nsc.tui.widgets.bulk_diff import BulkDiffModal
from nsc.tui.widgets.bulk_summary import BulkSummaryModal


class _SpyClient:
    def __init__(self, records: list[dict[str, Any]], fail_ids: tuple[Any, ...] = ()) -> None:
        self._records = records
        self._fail_ids = fail_ids
        self.patch_calls: list[dict[str, Any]] = []
        self.post_calls: list[dict[str, Any]] = []
        self.paginate_calls: list[tuple[str, dict[str, Any] | None]] = []

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any:
        self.paginate_calls.append((path, params))
        yield from self._records

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return {}

    def patch(
        self,
        path: str,
        *,
        json: Any | None = None,
        operation_id: str | None = None,
        sensitive_paths: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        self.patch_calls.append(
            {
                "path": path,
                "json": json,
                "operation_id": operation_id,
                "sensitive_paths": sensitive_paths,
            }
        )
        for fail_id in self._fail_ids:
            if path.endswith(f"/{fail_id}/"):
                raise NetBoxAPIError(
                    status_code=400,
                    url=path,
                    body_snippet="bad request",
                    headers={},
                )
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
async def test_shared_field_is_prepopulated_but_not_auto_included() -> None:
    client = _SpyClient([])
    app = _BulkApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        # both records share status="active" -> Select seeded
        assert screen.query_one("#field-status", Select).value == "active"
        # name/weight differ across records -> left blank
        assert screen.query_one("#field-name", Input).value == ""
        assert screen.query_one("#field-weight", Input).value == ""
        # seeding alone opts nothing in
        assert screen.bulk_set == {}


@pytest.mark.asyncio
async def test_including_a_prepopulated_field_uses_the_shared_value() -> None:
    client = _SpyClient([])
    app = _BulkApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#include-status", Switch).value = True  # opt in, unchanged
        await pilot.pause()
        assert screen.bulk_set == {"status": "active"}


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
async def test_include_boolean_at_default_false_lands_in_bulk_set() -> None:
    client = _SpyClient([])
    app = _BulkApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        # Include 'enabled' without ever toggling its field switch (stays False).
        screen.query_one("#include-enabled", Switch).value = True
        await pilot.pause()
        assert screen.bulk_set == {"enabled": False}


@pytest.mark.asyncio
async def test_include_seeds_numeric_int_value_from_widget() -> None:
    client = _SpyClient([])
    app = _BulkApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#field-weight", Input).value = "42"
        await pilot.pause()
        screen.query_one("#include-weight", Switch).value = True
        await pilot.pause()
        assert screen.bulk_set == {"weight": 42}
        assert isinstance(screen.bulk_set["weight"], int)


@pytest.mark.asyncio
async def test_include_non_numeric_weight_falls_back_to_raw_string() -> None:
    client = _SpyClient([])
    app = _BulkApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#field-weight", Input).value = "abc"
        await pilot.pause()
        screen.query_one("#include-weight", Switch).value = True
        await pilot.pause()
        assert screen.bulk_set == {"weight": "abc"}


@pytest.mark.asyncio
async def test_keyboard_preview_binding_pushes_diff_modal() -> None:
    client = _SpyClient([])
    app = _BulkApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#field-status", Select).value = "offline"
        await pilot.pause()
        screen.query_one("#include-status", Switch).value = True
        await pilot.pause()
        screen.focus_next()
        await pilot.press("p")
        await pilot.pause()
        assert isinstance(app.screen, BulkDiffModal)
        assert client.patch_calls == []


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


def _selected_heterogeneous() -> list[dict[str, Any]]:
    # Record #2 is already offline -> its status patch is empty (skipped).
    return [
        {"id": 1, "status": "active", "enabled": True, "weight": 10, "name": "sw1"},
        {"id": 2, "status": "offline", "enabled": False, "weight": 20, "name": "sw2"},
        {"id": 3, "status": "active", "enabled": True, "weight": 30, "name": "sw3"},
    ]


def _selected_all_active() -> list[dict[str, Any]]:
    # Every record needs the offline patch -> three patch calls.
    return [
        {"id": 1, "status": "active", "enabled": True, "weight": 10, "name": "sw1"},
        {"id": 2, "status": "active", "enabled": False, "weight": 20, "name": "sw2"},
        {"id": 3, "status": "active", "enabled": True, "weight": 30, "name": "sw3"},
    ]


class _BulkApp3(App[None]):
    def __init__(self, client: _SpyClient, selected: list[dict[str, Any]] | None = None) -> None:
        super().__init__()
        self._client = client
        self._selected = _selected_heterogeneous() if selected is None else selected

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
                self._selected,
            )
        )


def _screen3(app: _BulkApp3) -> BulkEditForm:
    screen = app.screen
    assert isinstance(screen, BulkEditForm)
    return screen


async def _stage_status_offline(pilot: Any, screen: BulkEditForm) -> None:
    screen.query_one("#field-status", Select).value = "offline"
    await pilot.pause()
    screen.query_one("#include-status", Switch).value = True
    await pilot.pause()


@pytest.mark.asyncio
async def test_confirm_patches_each_nonempty_record_and_skips_empty() -> None:
    client = _SpyClient([])
    app = _BulkApp3(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen3(app)
        await _stage_status_offline(pilot, screen)
        screen.action_preview()
        await pilot.pause()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

    # Record #2 already offline -> empty patch -> no patch call. #1 and #3 patched.
    assert [c["path"] for c in client.patch_calls] == [
        "/api/dcim/devices/1/",
        "/api/dcim/devices/3/",
    ]
    for call in client.patch_calls:
        assert call["json"] == {"status": "offline"}
        assert call["operation_id"] == "dcim_devices_partial_update"
        assert call["sensitive_paths"] == ("auth_key",)


@pytest.mark.asyncio
async def test_confirm_advances_progress_per_record() -> None:
    client = _SpyClient([])
    app = _BulkApp3(client, _selected_all_active())
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen3(app)
        await _stage_status_offline(pilot, screen)
        screen.action_preview()
        await pilot.pause()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert screen.progress_total == 3
        assert screen.progress_done == 3


@pytest.mark.asyncio
async def test_partial_failure_reports_summary_without_escaping() -> None:
    client = _SpyClient([], fail_ids=(3,))
    app = _BulkApp3(client, _selected_all_active())
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen3(app)
        await _stage_status_offline(pilot, screen)
        screen.action_preview()
        await pilot.pause()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        # All records attempted; no early stop on the failing one (#3).
        assert [c["path"] for c in client.patch_calls] == [
            "/api/dcim/devices/1/",
            "/api/dcim/devices/2/",
            "/api/dcim/devices/3/",
        ]
        summary = app.screen
        assert isinstance(summary, BulkSummaryModal)
        text = summary.render_text()
        assert "2 succeeded" in text
        assert "1 failed" in text
        assert "#3" in text
        assert "bad request" in text


@pytest.mark.asyncio
async def test_all_no_op_run_skips_every_record_and_reports_unchanged() -> None:
    # Every selected record already has status "offline" -> staging "offline" is a no-op.
    selected = [
        {"id": 1, "status": "offline", "enabled": True, "weight": 10, "name": "sw1"},
        {"id": 2, "status": "offline", "enabled": False, "weight": 20, "name": "sw2"},
    ]
    client = _SpyClient([])
    app = _BulkApp3(client, selected)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen3(app)
        await _stage_status_offline(pilot, screen)
        screen.action_preview()
        await pilot.pause()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert client.patch_calls == []
        assert screen.progress_total == 0
        summary = app.screen
        assert isinstance(summary, BulkSummaryModal)
        text = summary.render_text()
        assert "0 succeeded, 0 failed, 2 unchanged" in text


@pytest.mark.asyncio
async def test_partial_failure_dismiss_returns_to_list_and_clears_selection() -> None:
    records = _selected_all_active()
    client = _SpyClient(records, fail_ids=(3,))

    class _ListApp(App[None]):
        def compose(self) -> ComposeResult:
            yield Static("")

        async def on_mount(self) -> None:
            model = _model()
            await self.push_screen(ListScreen(model, client, "dcim", "devices", _update_op(model)))

    app = _ListApp()
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        list_screen = app.screen
        assert isinstance(list_screen, ListScreen)
        list_screen.selection.toggle(1)
        list_screen.selection.toggle(2)
        list_screen.selection.toggle(3)
        paginate_before = len(client.paginate_calls)

        list_screen.action_bulk_edit()
        await pilot.pause()
        form = app.screen
        assert isinstance(form, BulkEditForm)
        await _stage_status_offline(pilot, form)
        form.action_preview()
        await pilot.pause()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        summary = app.screen
        assert isinstance(summary, BulkSummaryModal)
        assert "1 failed" in summary.render_text()
        # Dismiss the partial-failure summary -> still returns to list and clears selection.
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is list_screen
        assert len(list_screen.selection) == 0
        assert len(client.paginate_calls) > paginate_before


@pytest.mark.asyncio
async def test_success_returns_to_list_reloads_and_clears_selection() -> None:
    records = _selected_heterogeneous()
    client = _SpyClient(records)

    class _ListApp(App[None]):
        def compose(self) -> ComposeResult:
            yield Static("")

        async def on_mount(self) -> None:
            model = _model()
            await self.push_screen(ListScreen(model, client, "dcim", "devices", _update_op(model)))

    app = _ListApp()
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        list_screen = app.screen
        assert isinstance(list_screen, ListScreen)
        list_screen.selection.toggle(1)
        list_screen.selection.toggle(3)
        paginate_before = len(client.paginate_calls)

        list_screen.action_bulk_edit()
        await pilot.pause()
        form = app.screen
        assert isinstance(form, BulkEditForm)
        await _stage_status_offline(pilot, form)
        form.action_preview()
        await pilot.pause()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        # Dismiss the summary modal -> back to the list.
        await pilot.press("enter")
        await pilot.pause()

        assert app.screen is list_screen
        assert len(list_screen.selection) == 0
        assert len(client.paginate_calls) > paginate_before


# ---- foreign-key chooser (issue #97) ---------------------------------------
#
# Writable FK fields type as `oneOf[integer, brief-ref]` -> UNKNOWN primitive ->
# `text` widget; the model carries no FK signal. Detection keys on the record's
# runtime nested object, so the bulk form must show a chooser (not a raw-id box)
# and render names in the diff.


def _fk_model() -> CommandModel:
    update_op = Operation(
        operation_id="dcim_devices_partial_update",
        http_method="PATCH",
        path="/api/dcim/devices/{id}/",
        request_body=RequestBodyShape(
            top_level="object",
            fields={
                "status": FieldShape(primitive=PrimitiveType.STRING, enum=["active", "offline"]),
                "role": FieldShape(primitive=PrimitiveType.UNKNOWN),
            },
        ),
    )
    devices = Resource(name="devices", update_op=update_op)
    roles_list = Operation(
        operation_id="dcim_device_roles_list",
        http_method="GET",
        path="/api/dcim/device-roles/",
    )
    roles = Resource(name="device-roles", list_op=roles_list)
    tag = Tag(name="dcim", resources={"devices": devices, "device-roles": roles})
    return CommandModel(info_title="t", info_version="1", schema_hash="h", tags={"dcim": tag})


def _role(role_id: int, display: str) -> dict[str, Any]:
    return {
        "id": role_id,
        "url": f"https://nb/api/dcim/device-roles/{role_id}/",
        "display": display,
    }


def _fk_selected_shared() -> list[dict[str, Any]]:
    role = _role(2, "Top of Rack Switch")
    return [
        {"id": 1, "status": "active", "role": role},
        {"id": 2, "status": "active", "role": role},
    ]


def _fk_selected_hetero() -> list[dict[str, Any]]:
    return [
        {"id": 1, "status": "active", "role": _role(2, "Top of Rack Switch")},
        {"id": 2, "status": "active", "role": _role(9, "Spine Switch")},
    ]


class _FkBulkApp(App[None]):
    def __init__(self, client: _SpyClient, selected: list[dict[str, Any]]) -> None:
        super().__init__()
        self._client = client
        self._selected = selected

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        model = _fk_model()
        op = model.tags["dcim"].resources["devices"].update_op
        assert op is not None
        await self.push_screen(
            BulkEditForm(model, self._client, "dcim", "devices", op, self._selected)
        )


@pytest.mark.asyncio
async def test_fk_field_renders_chooser_button_seeded_with_shared_name() -> None:
    client = _SpyClient([])
    app = _FkBulkApp(client, _fk_selected_shared())
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, BulkEditForm)
        # A picker button, not a free-text id box.
        button = screen.query_one("#fk-role", Button)
        assert not screen.query("#field-role")
        # Seeded with the shared FK's human label, not its id.
        assert "Top of Rack Switch" in str(button.label)


@pytest.mark.asyncio
async def test_fk_pick_stages_id_updates_label_and_diff_shows_names() -> None:
    client = _SpyClient([{"id": 5, "display": "Leaf Switch"}, {"id": 6, "display": "Spine"}])
    app = _FkBulkApp(client, _fk_selected_shared())
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, BulkEditForm)
        screen.query_one("#fk-role", Button).press()
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, RecordPicker)
        picker.query_one(ListView).index = 0  # Leaf Switch -> id 5
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        # Picking alone does not opt the field in (consistent with other widgets).
        assert screen.bulk_set == {}
        screen.query_one("#include-role", Switch).value = True
        await pilot.pause()
        assert screen.bulk_set == {"role": 5}
        assert "Leaf Switch" in str(screen.query_one("#fk-role", Button).label)
        # Diff renders names on both sides, not ids; patch still carries the id.
        screen.action_preview()
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, BulkDiffModal)
        text = modal.render_text()
        assert "Top of Rack Switch" in text
        assert "Leaf Switch" in text
        assert client.patch_calls == []


@pytest.mark.asyncio
async def test_include_shared_fk_without_picking_uses_shared_id() -> None:
    client = _SpyClient([])
    app = _FkBulkApp(client, _fk_selected_shared())
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, BulkEditForm)
        screen.query_one("#include-role", Switch).value = True
        await pilot.pause()
        # Seeds from the shared id (a no-op against the records), never None.
        assert screen.bulk_set == {"role": 2}


@pytest.mark.asyncio
async def test_include_heterogeneous_fk_without_picking_does_not_null() -> None:
    client = _SpyClient([])
    app = _FkBulkApp(client, _fk_selected_hetero())
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, BulkEditForm)
        # No shared value and nothing picked: must NOT inject None and null the FK.
        screen.query_one("#include-role", Switch).value = True
        await pilot.pause()
        assert "role" not in screen.bulk_set


@pytest.mark.asyncio
async def test_pick_then_setnull_clears_label_so_diff_matches_patch() -> None:
    # A nullable FK: pick a value (stages id + label), then ∅. The diff must show
    # the null, never the stale picked name.
    model = _fk_model()
    body = model.tags["dcim"].resources["devices"].update_op.request_body
    assert body is not None
    body.fields["role"] = FieldShape(primitive=PrimitiveType.UNKNOWN, nullable=True)
    client = _SpyClient([{"id": 5, "display": "Leaf Switch"}])

    class _NullableApp(App[None]):
        def compose(self) -> ComposeResult:
            yield Static("")

        async def on_mount(self) -> None:
            op = model.tags["dcim"].resources["devices"].update_op
            assert op is not None
            await self.push_screen(
                BulkEditForm(model, client, "dcim", "devices", op, _fk_selected_shared())
            )

    app = _NullableApp()
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, BulkEditForm)
        screen.query_one("#fk-role", Button).press()
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, RecordPicker)
        picker.query_one(ListView).index = 0
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert screen._fk_labels.get("role") == "Leaf Switch"
        screen.query_one("#setnull-role", Button).press()
        await pilot.pause()
        screen.query_one("#include-role", Switch).value = True
        await pilot.pause()
        assert screen.bulk_set.get("role") is SET_NULL
        assert "role" not in screen._fk_labels
        screen.action_preview()
        await pilot.pause()
        text = app.screen.render_text()
        assert "Leaf Switch" not in text


@pytest.mark.asyncio
async def test_unresolvable_fk_falls_back_to_raw_id_input() -> None:
    # No matching list resource -> resolve_fk_target yields raw_id -> text box.
    model = _fk_model()
    model.tags["dcim"].resources.pop("device-roles")
    selected = _fk_selected_shared()

    class _RawApp(App[None]):
        def compose(self) -> ComposeResult:
            yield Static("")

        async def on_mount(self) -> None:
            op = model.tags["dcim"].resources["devices"].update_op
            assert op is not None
            await self.push_screen(
                BulkEditForm(model, _SpyClient([]), "dcim", "devices", op, selected)
            )

    app = _RawApp()
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, BulkEditForm)
        widget = screen.query_one("#field-role")
        assert isinstance(widget, Input)
        assert not screen.query("#fk-role")
        widget.value = "7"
        await pilot.pause()
        screen.query_one("#include-role", Switch).value = True
        await pilot.pause()
        assert screen.bulk_set == {"role": 7}
        assert isinstance(screen.bulk_set["role"], int)


# --- #134: per-field custom fields + tags multi-select in bulk edit ---

_CF_DEFS = {
    "tier": CustomFieldDef("tier", "Tier", type="select", choices=("gold", "silver")),
    "count": CustomFieldDef("count", "Count", type="integer"),
}
_TAGS = (TagDef("Prod", "prod", "ff0000"), TagDef("Edge", "edge", None))


def _cf_model() -> CommandModel:
    update_op = Operation(
        operation_id="dcim_devices_partial_update",
        http_method="PATCH",
        path="/api/dcim/devices/{id}/",
        request_body=RequestBodyShape(
            top_level="object",
            fields={
                "name": FieldShape(primitive=PrimitiveType.STRING),
                "custom_fields": FieldShape(primitive=PrimitiveType.OBJECT),
                "tags": FieldShape(primitive=PrimitiveType.ARRAY),
            },
        ),
    )
    devices = Resource(name="devices", update_op=update_op)
    return CommandModel(
        info_title="t",
        info_version="1",
        schema_hash="h",
        tags={"dcim": Tag(name="dcim", resources={"devices": devices})},
    )


class _CfBulkApp(App[None]):
    def __init__(
        self,
        client: _SpyClient,
        *,
        defs: dict[str, Any] | None = _CF_DEFS,
        tags: tuple[TagDef, ...] | None = _TAGS,
        selected: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__()
        self._client = client
        self._defs = defs
        self._tags = tags
        self._sel = selected or [
            {"id": 1, "name": "sw1", "custom_fields": {"tier": "silver", "count": 1}, "tags": []},
            {"id": 2, "name": "sw2", "custom_fields": {"tier": "silver", "count": 2}, "tags": []},
        ]

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        model = _cf_model()
        op = model.tags["dcim"].resources["devices"].update_op
        assert op is not None
        await self.push_screen(
            BulkEditForm(
                model,
                self._client,
                "dcim",
                "devices",
                op,
                self._sel,
                custom_field_defs=self._defs,
                available_tags=self._tags,
            )
        )


def _cf_screen(app: _CfBulkApp) -> BulkEditForm:
    screen = app.screen
    assert isinstance(screen, BulkEditForm)
    return screen


@pytest.mark.asyncio
async def test_custom_fields_expand_into_per_field_widgets_with_toggles() -> None:
    app = _CfBulkApp(_SpyClient([]))
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _cf_screen(app)
        assert isinstance(screen.query_one("#field-custom_fields-tier"), Select)
        assert isinstance(screen.query_one("#field-custom_fields-count"), Input)
        assert isinstance(screen.query_one("#include-custom_fields-tier"), Switch)
        # No single opaque custom_fields widget remains.
        assert not screen.query("#field-custom_fields")


@pytest.mark.asyncio
async def test_tags_render_as_selection_list() -> None:
    app = _CfBulkApp(_SpyClient([]))
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _cf_screen(app)
        assert isinstance(screen.query_one("#field-tags"), SelectionList)


@pytest.mark.asyncio
async def test_bulk_apply_nests_custom_field_value() -> None:
    client = _SpyClient([])
    app = _CfBulkApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _cf_screen(app)
        screen._included.add("custom_fields.tier")
        screen._values["custom_fields.tier"] = "gold"
        screen.action_preview()
        await pilot.pause()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
    assert client.patch_calls
    for call in client.patch_calls:
        assert call["json"] == {"custom_fields": {"tier": "gold"}}


@pytest.mark.asyncio
async def test_bulk_apply_sets_tags_as_name_slug_list() -> None:
    client = _SpyClient([])
    app = _CfBulkApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _cf_screen(app)
        screen._included.add("tags")
        screen._values["tags"] = tags_payload(("prod",), _TAGS)
        screen.action_preview()
        await pilot.pause()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
    assert client.patch_calls
    for call in client.patch_calls:
        assert call["json"] == {"tags": [{"name": "Prod", "slug": "prod"}]}


@pytest.mark.asyncio
async def test_bulk_falls_back_to_text_inputs_without_defs() -> None:
    app = _CfBulkApp(_SpyClient([]), defs=None, tags=None)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _cf_screen(app)
        # Degrades to the previous opaque single inputs, no crash.
        assert isinstance(screen.query_one("#field-custom_fields"), Input)
        assert isinstance(screen.query_one("#field-tags"), Input)
        assert not screen.query("#field-custom_fields-tier")
