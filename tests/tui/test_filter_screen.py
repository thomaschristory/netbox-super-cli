from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Select, Static

from nsc.model.command_model import Operation, Parameter, ParameterLocation
from nsc.tui.screens.filter import FilterScreen


def _op() -> Operation:
    return Operation(
        operation_id="x_list",
        http_method="GET",
        path="/api/x/",
        parameters=[
            Parameter(name="q", location=ParameterLocation.QUERY),
            Parameter(name="status", location=ParameterLocation.QUERY, enum=["active", "offline"]),
            Parameter(name="name", location=ParameterLocation.QUERY),
            Parameter(name="name__ic", location=ParameterLocation.QUERY),
        ],
    )


class _FilterApp(App[None]):
    def __init__(self, current: dict[str, str] | None = None) -> None:
        super().__init__()
        self.result: dict[str, str] | None = None
        self._current = current or {}

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        def _cb(result: dict[str, str] | None) -> None:
            self.result = result

        await self.push_screen(FilterScreen(_op(), self._current), _cb)


@pytest.mark.asyncio
async def test_common_form_renders_enum_as_select() -> None:
    app = _FilterApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.query_one("#f-status", Select) is not None
        assert app.screen.query_one("#f-name", Input) is not None


@pytest.mark.asyncio
async def test_opening_with_current_filters_prefills_state() -> None:
    app = _FilterApp({"status": "active"})
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FilterScreen)
        assert screen.state.as_params() == {"status": "active"}


@pytest.mark.asyncio
async def test_raw_line_submits_into_state_and_apply_returns_dict() -> None:
    app = _FilterApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FilterScreen)
        raw = screen.query_one("#raw", Input)
        raw.value = "status=offline name=sw1"
        await pilot.pause()
        screen.on_input_submitted(Input.Submitted(raw, raw.value))
        screen.action_apply()
        await pilot.pause()
    assert app.result == {"status": "offline", "name": "sw1"}


@pytest.mark.asyncio
async def test_clear_empties_state() -> None:
    app = _FilterApp({"status": "active"})
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FilterScreen)
        screen.action_clear()
        await pilot.pause()
        assert screen.state.as_params() == {}


@pytest.mark.asyncio
async def test_escape_dismisses_with_none() -> None:
    app = _FilterApp({"status": "active"})
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None
