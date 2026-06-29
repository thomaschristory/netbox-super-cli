from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Input, Label, ListView, Select, SelectionList, Static, Switch

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
from nsc.tui.forms import SET_NULL, compute_patch, tags_payload
from nsc.tui.screens.edit_form import EditForm
from nsc.tui.screens.record_picker import RecordPicker
from nsc.tui.widgets.diff import DiffModal


class _SpyClient:
    def __init__(self, records: list[dict[str, Any]], *, fail_on_write: bool = False) -> None:
        self._records = records
        self._fail_on_write = fail_on_write
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
        self.patch_calls.append(
            {
                "path": path,
                "json": json,
                "operation_id": operation_id,
                "sensitive_paths": sensitive_paths,
            }
        )
        if self._fail_on_write:
            raise NetBoxAPIError(status_code=400, url=path, body_snippet="bad request", headers={})
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
        if self._fail_on_write:
            raise NetBoxAPIError(status_code=400, url=path, body_snippet="bad request", headers={})
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
                "ratio": FieldShape(primitive=PrimitiveType.NUMBER),
                "name": FieldShape(primitive=PrimitiveType.STRING),
                "auth_key": FieldShape(primitive=PrimitiveType.STRING),
                "site": FieldShape(primitive=PrimitiveType.INTEGER),
                "gizmo_id": FieldShape(primitive=PrimitiveType.INTEGER),
            },
            sensitive_paths=("auth_key",),
        ),
    )
    create_op = Operation(
        operation_id="dcim_devices_create",
        http_method="POST",
        path="/api/dcim/devices/",
        request_body=update_op.request_body,
    )
    devices = Resource(name="devices", update_op=update_op, create_op=create_op)
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
    def __init__(
        self,
        client: _SpyClient,
        *,
        create: bool = False,
        record: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self._client = client
        self._create = create
        self._record = record

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        model = _model()
        resource = model.tags["dcim"].resources["devices"]
        op = resource.create_op if self._create else resource.update_op
        assert op is not None
        record = self._record if self._record is not None else ({} if self._create else _record())
        await self.push_screen(EditForm(model, self._client, "dcim", "devices", op, record))


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


@pytest.mark.asyncio
async def test_text_kind_fk_is_detected_from_nested_record_value() -> None:
    # Real writable FK fields type as oneOf[int, brief] -> UNKNOWN -> `text`.
    # Detection must key off the record's nested object, not a `number` kind.
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
    model = CommandModel(info_title="t", info_version="1", schema_hash="h", tags={"dcim": tag})
    record = {
        "id": 5,
        "role": {
            "id": 2,
            "url": "https://nb/api/dcim/device-roles/2/",
            "display": "Top of Rack Switch",
        },
    }

    class _RoleApp(App[None]):
        def compose(self) -> ComposeResult:
            yield Static("")

        async def on_mount(self) -> None:
            await self.push_screen(
                EditForm(model, _SpyClient([]), "dcim", "devices", update_op, record)
            )

    app = _RoleApp()
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, EditForm)
        # Renders a chooser button (not a free-text id box) and seeds the name.
        button = screen.query_one("#fk-role", Button)
        assert "Top of Rack Switch" in str(button.label)
        assert not screen.query("#field-role")


@pytest.mark.asyncio
async def test_save_pushes_diff_modal_with_only_changed_field() -> None:

    client = _SpyClient([])
    app = _EditApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#field-name", Input).value = "sw2"
        await pilot.pause()
        screen.action_save()
        await pilot.pause()
        assert isinstance(app.screen, DiffModal)
        fields = [row.field for row in app.screen._rows]
        assert fields == ["name"]
        assert client.patch_calls == []


@pytest.mark.asyncio
async def test_save_confirm_calls_patch_with_minimal_body() -> None:
    client = _SpyClient([])
    app = _EditApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#field-name", Input).value = "sw2"
        await pilot.pause()
        screen.action_save()
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert len(client.patch_calls) == 1
        call = client.patch_calls[0]
        assert call["path"] == "/api/dcim/devices/5/"
        assert call["json"] == {"name": "sw2"}
        assert call["operation_id"] == "dcim_devices_partial_update"
        assert call["sensitive_paths"] == ("auth_key",)


@pytest.mark.asyncio
async def test_save_api_error_notifies_keeps_form_and_staged() -> None:
    client = _SpyClient([], fail_on_write=True)
    app = _EditApp(client)
    notifications: list[tuple[str, Any]] = []
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        original_notify = screen.notify

        def _capture(message: str, *args: Any, **kwargs: Any) -> None:
            notifications.append((message, kwargs.get("severity")))
            original_notify(message, *args, **kwargs)

        screen.notify = _capture  # type: ignore[method-assign]
        screen.query_one("#field-name", Input).value = "sw2"
        await pilot.pause()
        screen.action_save()
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert len(client.patch_calls) == 1
        # On error the form is NOT dismissed and the staged change survives.
        assert app.screen is screen
        assert screen.staged.get("name") == "sw2"
        assert any(sev == "error" for _, sev in notifications)


@pytest.mark.asyncio
async def test_save_set_null_sends_none() -> None:
    client = _SpyClient([])
    app = _EditApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#setnull-weight", Button).press()
        await pilot.pause()
        screen.action_save()
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert len(client.patch_calls) == 1
        assert client.patch_calls[0]["json"] == {"weight": None}


@pytest.mark.asyncio
async def test_save_cancel_does_not_call_patch() -> None:
    client = _SpyClient([])
    app = _EditApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#field-name", Input).value = "sw2"
        await pilot.pause()
        screen.action_save()
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert client.patch_calls == []


@pytest.mark.asyncio
async def test_save_with_no_changes_notifies_and_skips_patch() -> None:

    client = _SpyClient([])
    app = _EditApp(client)
    notifications: list[str] = []
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        original_notify = screen.notify

        def _capture(message: str, *args: Any, **kwargs: Any) -> None:
            notifications.append(message)
            original_notify(message, *args, **kwargs)

        screen.notify = _capture  # type: ignore[method-assign]
        screen.action_save()
        await pilot.pause()
        assert not isinstance(app.screen, DiffModal)
        assert client.patch_calls == []
        assert any("no change" in m.lower() for m in notifications)


@pytest.mark.asyncio
async def test_create_mode_mounts_with_blank_enum() -> None:
    client = _SpyClient([])
    app = _EditApp(client, create=True)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        select = screen.query_one("#field-status", Select)
        assert select.value is Select.NULL


@pytest.mark.asyncio
async def test_edit_mounts_when_enum_value_not_in_choices() -> None:
    record = {**_record(), "status": "staged"}
    client = _SpyClient([])
    app = _EditApp(client, record=record)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        assert screen.query_one("#field-status", Select).value is Select.NULL


@pytest.mark.asyncio
async def test_select_change_stages_enum_choice() -> None:
    client = _SpyClient([])
    app = _EditApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#field-status", Select).value = "offline"
        await pilot.pause()
        assert screen.staged.get("status") == "offline"
        assert client.patch_calls == []


@pytest.mark.asyncio
async def test_clearing_select_stages_none() -> None:
    client = _SpyClient([])
    app = _EditApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#field-status", Select).value = Select.NULL
        await pilot.pause()
        assert screen.staged.get("status") is None


@pytest.mark.asyncio
async def test_float_field_stages_as_float() -> None:
    client = _SpyClient([])
    app = _EditApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#field-ratio", Input).value = "1.5"
        await pilot.pause()
        assert screen.staged.get("ratio") == 1.5
        assert isinstance(screen.staged["ratio"], float)


@pytest.mark.asyncio
async def test_clearing_numeric_input_stages_none() -> None:
    client = _SpyClient([])
    app = _EditApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        weight = screen.query_one("#field-weight", Input)
        weight.value = ""
        await pilot.pause()
        assert screen.staged.get("weight") is None


@pytest.mark.asyncio
async def test_non_numeric_input_in_number_field_stays_string() -> None:
    client = _SpyClient([])
    app = _EditApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        ratio = screen.query_one("#field-ratio", Input)
        ratio.value = "abc"
        await pilot.pause()
        assert screen.staged.get("ratio") == "abc"


@pytest.mark.asyncio
async def test_unresolvable_fk_renders_raw_id_input_and_stages_int() -> None:
    client = _SpyClient([])
    app = _EditApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        widget = screen.query_one("#field-gizmo_id")
        assert isinstance(widget, Input)
        assert not isinstance(widget, Button)
        assert len(screen.query(".edit-fk-hint")) >= 1
        widget.value = "42"
        await pilot.pause()
        assert screen.staged.get("gizmo_id") == 42
        assert isinstance(screen.staged["gizmo_id"], int)


@pytest.mark.asyncio
async def test_non_numeric_raw_fk_stays_string() -> None:
    client = _SpyClient([])
    app = _EditApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        widget = screen.query_one("#field-gizmo_id", Input)
        widget.value = "nope"
        await pilot.pause()
        assert screen.staged.get("gizmo_id") == "nope"


@pytest.mark.asyncio
async def test_fk_pick_stages_id_and_patches_then_omits_when_same() -> None:
    client = _SpyClient([{"id": 3, "display": "HQ"}, {"id": 4, "display": "Branch"}])
    app = _EditApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#fk-site", Button).press()
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, RecordPicker)
        lv = picker.query_one(ListView)
        lv.index = 1
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert screen.staged.get("site") == 4
        screen.action_save()
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert len(client.patch_calls) == 1
        assert client.patch_calls[0]["json"] == {"site": 4}


@pytest.mark.asyncio
async def test_fk_repick_same_id_yields_no_patch_key() -> None:
    client = _SpyClient([{"id": 3, "display": "HQ"}, {"id": 4, "display": "Branch"}])
    app = _EditApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#fk-site", Button).press()
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, RecordPicker)
        picker.query_one(ListView).index = 0
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert screen.staged.get("site") == 3
        assert "site" not in compute_patch(_record(), screen.staged)


@pytest.mark.asyncio
async def test_go_back_with_staged_changes_prompts_confirm() -> None:
    client = _SpyClient([])
    app = _EditApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#field-name", Input).value = "sw2"
        await pilot.pause()
        screen.action_go_back()
        await pilot.pause()
        assert app.screen is not screen
        assert isinstance(screen, EditForm)
        assert app.screen.__class__.__name__ == "ConfirmModal"


@pytest.mark.asyncio
async def test_go_back_without_changes_dismisses_immediately() -> None:
    client = _SpyClient([])
    app = _EditApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.action_go_back()
        await pilot.pause()
        assert app.screen is not screen


# --- #134: per-field custom fields + tags multi-select in single edit ---

_CF_DEFS = {"tier": CustomFieldDef("tier", "Tier", type="select", choices=("gold", "silver"))}
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


class _CfEditApp(App[None]):
    def __init__(self, client: _SpyClient, record: dict[str, Any]) -> None:
        super().__init__()
        self._client = client
        self._record = record

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        model = _cf_model()
        op = model.tags["dcim"].resources["devices"].update_op
        assert op is not None
        await self.push_screen(
            EditForm(
                model,
                self._client,
                "dcim",
                "devices",
                op,
                self._record,
                custom_field_defs=_CF_DEFS,
                available_tags=_TAGS,
            )
        )


def _cf_edit_screen(app: _CfEditApp) -> EditForm:
    screen = app.screen
    assert isinstance(screen, EditForm)
    return screen


@pytest.mark.asyncio
async def test_edit_expands_custom_field_widget() -> None:
    record = {"id": 5, "name": "sw1", "custom_fields": {"tier": "silver"}, "tags": []}
    app = _CfEditApp(_SpyClient([]), record)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _cf_edit_screen(app)
        tier = screen.query_one("#field-custom_fields-tier", Select)
        assert tier.value == "silver"
        assert isinstance(screen.query_one("#field-tags"), SelectionList)


@pytest.mark.asyncio
async def test_edit_custom_field_row_shows_human_label_not_raw_key() -> None:
    record = {"id": 5, "name": "sw1", "custom_fields": {"tier": "silver"}, "tags": []}
    app = _CfEditApp(_SpyClient([]), record)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _cf_edit_screen(app)
        labels = {w.render().plain for w in screen.query(".edit-label").results(Label)}
        assert "Tier" in labels
        assert "custom_fields.tier" not in labels


@pytest.mark.asyncio
async def test_edit_diff_modal_shows_custom_field_label_not_raw_key() -> None:
    record = {"id": 5, "name": "sw1", "custom_fields": {"tier": "silver"}, "tags": []}
    app = _CfEditApp(_SpyClient([]), record)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _cf_edit_screen(app)
        screen.staged["custom_fields.tier"] = "gold"
        screen.action_save()
        await pilot.pause()
        assert isinstance(app.screen, DiffModal)
        fields = [row.field for row in app.screen._rows]
        assert fields == ["Tier"]


@pytest.mark.asyncio
async def test_edit_saves_custom_field_nested() -> None:
    client = _SpyClient([])
    record = {"id": 5, "name": "sw1", "custom_fields": {"tier": "silver"}, "tags": []}
    app = _CfEditApp(client, record)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _cf_edit_screen(app)
        screen.staged["custom_fields.tier"] = "gold"
        screen.action_save()
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
    assert len(client.patch_calls) == 1
    assert client.patch_calls[0]["json"] == {"custom_fields": {"tier": "gold"}}


@pytest.mark.asyncio
async def test_edit_saves_tags_as_name_slug_list() -> None:
    client = _SpyClient([])
    record = {
        "id": 5,
        "name": "sw1",
        "custom_fields": {},
        "tags": [{"slug": "prod", "name": "Prod"}],
    }
    app = _CfEditApp(client, record)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _cf_edit_screen(app)
        screen.staged["tags"] = tags_payload(("prod", "edge"), _TAGS)
        screen.action_save()
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
    assert len(client.patch_calls) == 1
    assert client.patch_calls[0]["json"] == {
        "tags": [{"name": "Prod", "slug": "prod"}, {"name": "Edge", "slug": "edge"}]
    }


@pytest.mark.asyncio
async def test_edit_unchanged_tag_selection_stages_nothing() -> None:
    record = {
        "id": 5,
        "name": "sw1",
        "custom_fields": {},
        "tags": [{"slug": "prod", "name": "Prod"}],
    }
    app = _CfEditApp(_SpyClient([]), record)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = _cf_edit_screen(app)
        # The pre-seeded selection firing on mount must not stage a tags change.
        assert "tags" not in screen.staged


_CF_DEFS_MS = {
    "envs": CustomFieldDef("envs", "Envs", type="multiselect", choices=("dev", "prod", "qa")),
}


class _CfMsEditApp(App[None]):
    def __init__(self, client: _SpyClient, record: dict[str, Any]) -> None:
        super().__init__()
        self._client = client
        self._record = record

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        model = _cf_model()
        op = model.tags["dcim"].resources["devices"].update_op
        assert op is not None
        await self.push_screen(
            EditForm(
                model,
                self._client,
                "dcim",
                "devices",
                op,
                self._record,
                custom_field_defs=_CF_DEFS_MS,
                available_tags=_TAGS,
            )
        )


@pytest.mark.asyncio
async def test_edit_multiselect_custom_field_preseeds_current_values() -> None:
    record = {"id": 5, "name": "sw1", "custom_fields": {"envs": ["dev", "qa"]}, "tags": []}
    app = _CfMsEditApp(_SpyClient([]), record)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, EditForm)
        widget = screen.query_one("#field-custom_fields-envs", SelectionList)
        assert set(widget.selected) == {"dev", "qa"}
        # Pre-seeded selection that is unchanged stages nothing.
        assert "custom_fields.envs" not in screen.staged
