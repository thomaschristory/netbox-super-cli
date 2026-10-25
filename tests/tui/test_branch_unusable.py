"""A branch merged/deleted mid-session is reported as such, not as a bare 400 (#176)."""

from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from nsc.http.errors import NetBoxAPIError
from nsc.tui.app import NscTuiApp
from nsc.tui.bulk import RecordChange, apply_bulk
from nsc.tui.screens.global_search import GlobalSearchScreen
from tests.tui.test_app import _model
from tests.tui.test_global_search import _model as _search_model

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
