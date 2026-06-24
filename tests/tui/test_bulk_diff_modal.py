from __future__ import annotations

from typing import Any

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Select, Static, Switch

from nsc.model.command_model import (
    CommandModel,
    FieldShape,
    Operation,
    PrimitiveType,
    RequestBodyShape,
    Resource,
    Tag,
)
from nsc.tui.bulk import RecordChange, bulk_diff
from nsc.tui.forms import DiffRow
from nsc.tui.screens.bulk_edit_form import BulkEditForm
from nsc.tui.widgets.bulk_diff import BulkDiffModal


class _BulkDiffApp(App[None]):
    def __init__(self, changes: list[RecordChange]) -> None:
        super().__init__()
        self._changes = changes
        self.result: bool | None = None

    def compose(self) -> ComposeResult:
        yield from ()

    async def on_mount(self) -> None:
        def _store(value: bool) -> None:
            self.result = value

        await self.push_screen(BulkDiffModal(self._changes), _store)


def _changes() -> list[RecordChange]:
    return [
        RecordChange(
            record_id=1,
            patch={"status": "offline"},
            rows=[DiffRow(field="status", old_display="active", new_display="offline")],
        ),
        RecordChange(
            record_id=2,
            patch={},
            rows=[],
        ),
        RecordChange(
            record_id=3,
            patch={"auth_key": "secret"},
            rows=[DiffRow(field="auth_key", old_display="****", new_display="****")],
        ),
    ]


def test_bulk_diff_modal_empty_changes_renders_no_changes() -> None:
    assert "No changes." in BulkDiffModal([]).render_text()


def test_bulk_diff_modal_renders_per_record_block_with_id_and_rows() -> None:
    text = BulkDiffModal(_changes()).render_text()
    assert "record #1" in text
    assert "status: active -> offline" in text
    assert "record #3" in text


def test_bulk_diff_modal_record_with_no_changes_marked_unchanged() -> None:
    text = BulkDiffModal(_changes()).render_text()
    assert "record #2" in text
    assert "unchanged" in text


def test_bulk_diff_modal_masks_sensitive_values() -> None:
    text = BulkDiffModal(_changes()).render_text()
    assert "auth_key: **** -> ****" in text
    assert "secret" not in text


def test_bulk_diff_modal_escapes_bracket_content_in_values() -> None:
    changes = [
        RecordChange(
            record_id=1,
            patch={"comment": "[see note]"},
            rows=[DiffRow(field="comment", old_display="[/]", new_display="[see note]")],
        ),
    ]
    text = BulkDiffModal(changes).render_text()
    assert "[/]" in text
    assert "[see note]" in text
    rendered = Text.from_markup(text)
    assert "[/]" in rendered.plain
    assert "[see note]" in rendered.plain


def test_bulk_diff_modal_renders_values_from_pure_bulk_diff() -> None:
    selected: list[dict[str, Any]] = [
        {"id": 1, "status": "active"},
        {"id": 2, "status": "offline"},
    ]
    changes = bulk_diff(selected, {"status": "offline"}, ())
    text = BulkDiffModal(changes).render_text()
    assert "record #1" in text
    assert "status: active -> offline" in text
    assert "record #2" in text
    assert "unchanged" in text


@pytest.mark.asyncio
async def test_bulk_diff_modal_confirm_enter_dismisses_true() -> None:
    app = _BulkDiffApp(_changes())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, BulkDiffModal)
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, BulkDiffModal)
        assert app.result is True


@pytest.mark.asyncio
async def test_bulk_diff_modal_confirm_key_y_dismisses_true() -> None:
    app = _BulkDiffApp(_changes())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert app.result is True


@pytest.mark.asyncio
async def test_bulk_diff_modal_escape_dismisses_false() -> None:
    app = _BulkDiffApp(_changes())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, BulkDiffModal)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, BulkDiffModal)
        assert app.result is False


@pytest.mark.asyncio
async def test_bulk_diff_modal_cancel_key_n_dismisses_false() -> None:
    app = _BulkDiffApp(_changes())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert app.result is False


class _SpyClient:
    def __init__(self) -> None:
        self.patch_calls: list[dict[str, Any]] = []

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any:
        yield from ()

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


def _model() -> CommandModel:
    update_op = Operation(
        operation_id="dcim_devices_partial_update",
        http_method="PATCH",
        path="/api/dcim/devices/{id}/",
        request_body=RequestBodyShape(
            top_level="object",
            fields={
                "status": FieldShape(primitive=PrimitiveType.STRING, enum=["active", "offline"]),
            },
            sensitive_paths=(),
        ),
    )
    devices = Resource(name="devices", update_op=update_op)
    tag = Tag(name="dcim", resources={"devices": devices})
    return CommandModel(info_title="t", info_version="1", schema_hash="h", tags={"dcim": tag})


def _update_op(model: CommandModel) -> Operation:
    op = model.tags["dcim"].resources["devices"].update_op
    assert op is not None
    return op


class _BulkEditApp(App[None]):
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
                [
                    {"id": 1, "status": "active"},
                    {"id": 2, "status": "active"},
                ],
            )
        )


@pytest.mark.asyncio
async def test_preview_always_pushes_bulk_diff_modal_before_patch() -> None:
    client = _SpyClient()
    app = _BulkEditApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, BulkEditForm)
        screen.query_one("#field-status", Select).value = "offline"
        await pilot.pause()
        screen.query_one("#include-status", Switch).value = True
        await pilot.pause()
        screen.action_preview()
        await pilot.pause()
        assert isinstance(app.screen, BulkDiffModal)
        assert client.patch_calls == []
