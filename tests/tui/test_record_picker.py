from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, ListView, Static

from nsc.model.command_model import Operation
from nsc.tui.screens.record_picker import RecordPicker


class _FakeClient:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = records
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any:
        self.calls.append((path, params))
        query = (params or {}).get("q") if params else None
        for record in self._records:
            if query and query.lower() not in str(record.get("display", "")).lower():
                continue
            yield record


def _op() -> Operation:
    return Operation(
        operation_id="dcim_sites_list",
        http_method="GET",
        path="/api/dcim/sites/",
    )


class _PickerApp(App[None]):
    def __init__(self, client: _FakeClient, *, current_id: int | None = None) -> None:
        super().__init__()
        self._client = client
        self._current_id = current_id
        self.chosen: tuple[int, str] | None = None
        self.dismissed = False

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        def _record(result: tuple[int, str] | None) -> None:
            self.dismissed = True
            self.chosen = result

        await self.push_screen(RecordPicker(self._client, _op(), self._current_id), _record)


def _records() -> list[dict[str, Any]]:
    return [
        {"id": 1, "display": "HQ"},
        {"id": 2, "display": "Branch"},
        {"id": 3, "display": "Headquarters East"},
    ]


@pytest.mark.asyncio
async def test_mount_populates_list() -> None:
    client = _FakeClient(_records())
    app = _PickerApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        lv = app.screen.query_one(ListView)
        assert len(lv) == 3
        assert client.calls[0][0] == "/api/dcim/sites/"


@pytest.mark.asyncio
async def test_typing_requeries_with_q_param_and_repopulates() -> None:
    client = _FakeClient(_records())
    app = _PickerApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen.query_one(Input).focus()
        await pilot.pause()
        await pilot.press("H", "Q")
        await pilot.pause()
        last_params = client.calls[-1][1]
        assert last_params is not None
        assert last_params.get("q") == "HQ"
        lv = app.screen.query_one(ListView)
        assert len(lv) == 1


@pytest.mark.asyncio
async def test_enter_dismisses_with_highlighted_record() -> None:
    client = _FakeClient(_records())
    app = _PickerApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen.query_one(Input).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert app.chosen == (1, "HQ")


@pytest.mark.asyncio
async def test_escape_dismisses_with_none() -> None:
    client = _FakeClient(_records())
    app = _PickerApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert app.dismissed is True
    assert app.chosen is None


@pytest.mark.asyncio
async def test_empty_result_set_enter_is_noop() -> None:
    client = _FakeClient([])
    app = _PickerApp(client)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert len(app.screen.query_one(ListView)) == 0
        app.screen.query_one(Input).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.dismissed is False
        assert app.chosen is None


@pytest.mark.asyncio
async def test_current_id_highlights_matching_row() -> None:
    client = _FakeClient(_records())
    app = _PickerApp(client, current_id=2)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.query_one(ListView).index == 1
