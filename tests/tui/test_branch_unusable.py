"""A branch merged/deleted mid-session is reported as such, not as a bare 400 (#176)."""

from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from nsc.http.errors import NetBoxAPIError
from nsc.tui.app import NscTuiApp
from nsc.tui.bulk import RecordChange, apply_bulk
from nsc.tui.screens.bulk_edit_form import BulkEditForm
from nsc.tui.screens.detail import DetailScreen
from nsc.tui.screens.edit_form import EditForm
from nsc.tui.screens.global_search import GlobalSearchScreen
from nsc.tui.screens.list import ListScreen
from nsc.tui.screens.record_picker import RecordPicker
from nsc.tui.widgets.bulk_summary import BulkSummaryModal
from tests.tui.test_app import _model
from tests.tui.test_bulk_edit_form import _BulkApp3, _selected_all_active, _stage_status_offline
from tests.tui.test_bulk_edit_form import _SpyClient as _BulkSpyClient
from tests.tui.test_detail_screen import _DetailApp
from tests.tui.test_detail_screen import _SpyClient as _DetailSpyClient
from tests.tui.test_edit_form import _EditApp
from tests.tui.test_edit_form import _SpyClient as _EditSpyClient
from tests.tui.test_global_search import _model as _search_model
from tests.tui.test_list_screen import _GatedPagedClient, _ListApp, _settle
from tests.tui.test_record_picker import _FakeClient as _PickerFakeClient
from tests.tui.test_record_picker import _PickerApp

_MERGED = "Branch b1 is not ready for use (status: merged)"


class _RaisingClient:
    def __init__(self, body: str) -> None:
        self.body = body
        self.calls: list[str] = []

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any:
        self.calls.append(path)
        raise NetBoxAPIError(status_code=400, url=path, body_snippet=self.body, headers={})


def _messages(app: App[Any]) -> list[str]:
    return [n.message for n in app._notifications]


@pytest.mark.asyncio
async def test_list_load_explains_unusable_branch() -> None:
    app = NscTuiApp(_model(), _RaisingClient(_MERGED), initial_resource="devices", branch="b1")
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        messages = _messages(app)
        assert any("branch 'b1' is no longer usable (status: merged)" in m for m in messages)
        assert not any(m.startswith("API 400") for m in messages)


@pytest.mark.asyncio
async def test_list_load_keeps_validation_400_unchanged_on_a_branch() -> None:
    client = _RaisingClient('{"name": ["Bad filter."]}')
    app = NscTuiApp(_model(), client, initial_resource="devices", branch="b1")
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "API 400 — name: Bad filter." in _messages(app)


@pytest.mark.asyncio
async def test_list_load_without_branch_renders_raw_body() -> None:
    app = NscTuiApp(
        _model(), _RaisingClient("Invalid branch identifier"), initial_resource="devices"
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "API 400 — Invalid branch identifier" in _messages(app)


class _SearchApp(App[None]):
    active_branch = "b1"

    def __init__(self, client: _RaisingClient) -> None:
        super().__init__()
        self.client = client

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        await self.push_screen(GlobalSearchScreen(_search_model(), self.client))


@pytest.mark.asyncio
async def test_global_search_stops_and_explains_unusable_branch() -> None:
    client = _RaisingClient("Invalid branch identifier")
    app = _SearchApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, GlobalSearchScreen)
        await screen._run_search("sw")
        await pilot.pause()
        assert len(client.calls) == 1
        assert any(
            "branch 'b1' is no longer usable (deleted or not found)" in m for m in _messages(app)
        )


def test_apply_bulk_uses_describe_for_failures() -> None:
    def _patch(change: RecordChange) -> None:
        raise NetBoxAPIError(status_code=400, url="u", body_snippet=_MERGED, headers={})

    result = apply_bulk(
        [RecordChange(record_id=1, patch={"status": "active"}, rows=[])],
        _patch,
        describe=lambda exc: f"described: {type(exc).__name__}",
    )
    assert [f.error for f in result.failures] == ["described: NetBoxAPIError"]


def _merged_error(path: str) -> NetBoxAPIError:
    return NetBoxAPIError(status_code=400, url=path, body_snippet=_MERGED, headers={})


def _assert_explains_merged(messages: list[str]) -> None:
    assert any("branch 'b1' is no longer usable (status: merged)" in m for m in messages), messages
    assert not any("API 400" in m for m in messages), messages


class _DeadBranchDetailClient(_DetailSpyClient):
    def patch(self, path: str, **kwargs: Any) -> dict[str, Any]:
        self.patch_calls.append({"path": path})
        raise _merged_error(path)

    def delete(self, path: str, **kwargs: Any) -> Any:
        self.delete_calls.append({"path": path})
        raise _merged_error(path)


class _BranchDetailApp(_DetailApp):
    active_branch = "b1"

    def __init__(self) -> None:
        super().__init__()
        self.client = _DeadBranchDetailClient()


@pytest.mark.asyncio
async def test_detail_save_explains_unusable_branch() -> None:
    app = _BranchDetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DetailScreen)
        screen.staged = {"name": "sw1-renamed"}
        screen.action_save_all()
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert app.client.patch_calls
        _assert_explains_merged(_messages(app))


@pytest.mark.asyncio
async def test_detail_delete_explains_unusable_branch() -> None:
    app = _BranchDetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert app.client.delete_calls
        _assert_explains_merged(_messages(app))


class _DeadBranchEditClient(_EditSpyClient):
    def patch(self, path: str, **kwargs: Any) -> dict[str, Any]:
        self.patch_calls.append({"path": path})
        raise _merged_error(path)


class _BranchEditApp(_EditApp):
    active_branch = "b1"


@pytest.mark.asyncio
async def test_edit_form_save_explains_unusable_branch() -> None:
    client = _DeadBranchEditClient([])
    app = _BranchEditApp(client)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, EditForm)
        screen.query_one("#field-name", Input).value = "sw2"
        await pilot.pause()
        screen.action_save()
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert client.patch_calls
        _assert_explains_merged(_messages(app))


class _DeadBranchBulkClient(_BulkSpyClient):
    def patch(self, path: str, **kwargs: Any) -> dict[str, Any]:
        self.patch_calls.append({"path": path})
        raise _merged_error(path)


class _BranchBulkApp(_BulkApp3):
    active_branch = "b1"


@pytest.mark.asyncio
async def test_bulk_edit_summary_explains_unusable_branch() -> None:
    client = _DeadBranchBulkClient([])
    app = _BranchBulkApp(client, _selected_all_active())
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, BulkEditForm)
        await _stage_status_offline(pilot, screen)
        screen.action_preview()
        await pilot.pause()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        summary = app.screen
        assert isinstance(summary, BulkSummaryModal)
        text = summary.render_text()
        assert "3 failed" in text
        assert "branch 'b1' is no longer usable (status: merged)" in text
        assert "API 400" not in text


class _DeadBranchPickerClient(_PickerFakeClient):
    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any:
        self.calls.append((path, params))
        raise _merged_error(path)


class _BranchPickerApp(_PickerApp):
    active_branch = "b1"


@pytest.mark.asyncio
async def test_record_picker_load_explains_unusable_branch() -> None:
    client = _DeadBranchPickerClient([])
    app = _BranchPickerApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, RecordPicker)
        await screen._query("anything")
        await pilot.pause()
        _assert_explains_merged(_messages(app))


class _DeadBranchPagedClient(_GatedPagedClient):
    dead_from = 10**9

    def _fetch(self, path: str, params: dict[str, Any] | None) -> dict[str, Any]:
        if int((params or {}).get("offset", 0)) >= self.dead_from:
            raise _merged_error(path)
        return super()._fetch(path, params)


class _BranchListApp(_ListApp):
    active_branch = "b1"


@pytest.mark.asyncio
async def test_list_load_more_explains_unusable_branch() -> None:
    client = _DeadBranchPagedClient(300)
    app = _BranchListApp(client)
    async with app.run_test() as pilot:
        await _settle(app, pilot)
        screen = app.screen
        assert isinstance(screen, ListScreen)
        client.dead_from = 100
        screen.action_load_more()
        await _settle(app, pilot)
        _assert_explains_merged(_messages(app))
