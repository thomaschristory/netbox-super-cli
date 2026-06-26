from __future__ import annotations

from typing import Any

import pytest
from textual.widgets import DataTable

from nsc.model.command_model import CommandModel, Operation, Resource, Tag
from nsc.tui.app import NscTuiApp
from nsc.tui.screens.global_search import GlobalSearchScreen
from nsc.tui.screens.list import ListScreen
from nsc.tui.screens.picker import ResourcePicker
from nsc.tui.widgets.help import HelpOverlay


class _FakeClient:
    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any:
        return iter([{"id": 1, "name": "sw1"}])


def _model() -> CommandModel:
    op = Operation(
        operation_id="d_list",
        http_method="GET",
        path="/api/dcim/devices/",
        default_columns=["id", "name"],
    )
    tag = Tag(name="dcim", resources={"devices": Resource(name="devices", list_op=op)})
    return CommandModel(info_title="t", info_version="1", schema_hash="h", tags={"dcim": tag})


@pytest.mark.asyncio
async def test_app_opens_resource_directly_when_named() -> None:
    app = NscTuiApp(_model(), _FakeClient(), initial_resource="devices")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ListScreen)


@pytest.mark.asyncio
async def test_saved_column_prefs_are_applied_on_launch() -> None:
    app = NscTuiApp(
        _model(),
        _FakeClient(),
        initial_resource="devices",
        column_prefs={"dcim": {"devices": ["name"]}},
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        screen = app.screen
        assert isinstance(screen, ListScreen)
        table = screen.query_one("#rows", DataTable)
        labels = [str(col.label) for col in table.columns.values()]
        assert labels == [" ", "name"]  # marker column + only the saved column


@pytest.mark.asyncio
async def test_save_columns_updates_in_memory_prefs() -> None:
    app = NscTuiApp(_model(), _FakeClient(), initial_resource="devices")
    async with app.run_test() as pilot:
        await pilot.pause()
        app.save_columns("dcim", "devices", ["name", "id"])
        assert app.columns_for("dcim", "devices") == ["name", "id"]


@pytest.mark.asyncio
async def test_saved_searches_for_reads_memory() -> None:
    app = NscTuiApp(
        _model(),
        _FakeClient(),
        initial_resource="devices",
        saved_searches={"dcim": {"devices": {"active-sw": {"status": "active"}}}},
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.saved_searches_for("dcim", "devices") == {"active-sw": {"status": "active"}}
        assert app.saved_searches_for("dcim", "racks") == {}


@pytest.mark.asyncio
async def test_save_search_updates_memory_and_callback() -> None:
    calls: list[tuple[str, str, str, dict[str, str]]] = []
    app = NscTuiApp(
        _model(),
        _FakeClient(),
        initial_resource="devices",
        save_search=lambda t, r, n, p: calls.append((t, r, n, p)),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        app.save_search("dcim", "devices", "active-sw", {"status": "active"})
        assert app.saved_searches_for("dcim", "devices") == {"active-sw": {"status": "active"}}
        assert calls == [("dcim", "devices", "active-sw", {"status": "active"})]


@pytest.mark.asyncio
async def test_delete_search_updates_memory_and_callback() -> None:
    calls: list[tuple[str, str, str]] = []
    app = NscTuiApp(
        _model(),
        _FakeClient(),
        initial_resource="devices",
        saved_searches={"dcim": {"devices": {"active-sw": {"status": "active"}}}},
        delete_search=lambda t, r, n: calls.append((t, r, n)),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        app.delete_search("dcim", "devices", "active-sw")
        assert app.saved_searches_for("dcim", "devices") == {}
        assert calls == [("dcim", "devices", "active-sw")]


@pytest.mark.asyncio
async def test_ctrl_f_opens_global_search_from_any_screen() -> None:
    app = NscTuiApp(_model(), _FakeClient(), initial_resource="devices")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ListScreen)
        await pilot.press("ctrl+f")
        await pilot.pause()
        assert isinstance(app.screen, GlobalSearchScreen)


@pytest.mark.asyncio
async def test_ctrl_f_opens_global_search_from_the_picker() -> None:
    app = NscTuiApp(_model(), _FakeClient(), initial_resource=None)  # lands on the picker
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ResourcePicker)
        await pilot.press("ctrl+f")
        await pilot.pause()
        assert isinstance(app.screen, GlobalSearchScreen)


@pytest.mark.asyncio
async def test_app_lands_on_picker_without_resource() -> None:
    app = NscTuiApp(_model(), _FakeClient(), initial_resource=None)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ResourcePicker)


@pytest.mark.asyncio
async def test_help_action_pushes_overlay() -> None:
    app = NscTuiApp(_model(), _FakeClient(), initial_resource="devices")
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.action_request_help()
        await pilot.pause()
        assert isinstance(app.screen, HelpOverlay)


@pytest.mark.asyncio
async def test_ctrl_p_opens_resource_picker_not_command_palette() -> None:
    app = NscTuiApp(_model(), _FakeClient(), initial_resource="devices")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(app.screen, ResourcePicker)


@pytest.mark.asyncio
async def test_bare_p_does_not_open_picker() -> None:
    app = NscTuiApp(_model(), _FakeClient(), initial_resource="devices")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        assert isinstance(app.screen, ListScreen)


@pytest.mark.asyncio
async def test_q_quits_from_focused_list() -> None:
    app = NscTuiApp(_model(), _FakeClient(), initial_resource="devices")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ListScreen)
        await pilot.press("q")
        await pilot.pause()
    assert app.return_code is not None
