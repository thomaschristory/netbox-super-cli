from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Input, Label, ListView, Select, Static

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


@pytest.mark.asyncio
async def test_enum_select_prefills_value_and_options() -> None:
    app = _FilterApp({"status": "active"})
    async with app.run_test() as pilot:
        await pilot.pause()
        select = app.screen.query_one("#f-status", Select)
        assert select.value == "active"
        assert [opt for opt in select._options if opt[1] is not Select.NULL] == [
            ("active", "active"),
            ("offline", "offline"),
        ]


@pytest.mark.asyncio
async def test_out_of_enum_value_remains_visible_and_keeps_state() -> None:
    app = _FilterApp({"status": "WEIRD"})
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FilterScreen)
        select = screen.query_one("#f-status", Select)
        assert select.value == "WEIRD"
        assert screen.state.as_params() == {"status": "WEIRD"}


@pytest.mark.asyncio
async def test_raw_submit_renders_chips() -> None:
    app = _FilterApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FilterScreen)
        raw = screen.query_one("#raw", Input)
        raw.value = "status=offline name=sw1"
        screen.on_input_submitted(Input.Submitted(raw, raw.value))
        await pilot.pause()
        chips = screen.query_one("#chips")
        rows = chips.query(Horizontal)
        assert len(rows) == 2
        labels = {str(label.render()) for label in chips.query(Label)}
        assert "status = offline" in labels
        assert "name = sw1" in labels
        assert screen.query_one("#rm-status", Button) is not None
        assert screen.query_one("#rm-name", Button) is not None


@pytest.mark.asyncio
async def test_chip_remove_drops_only_that_filter_and_resyncs_widget() -> None:
    app = _FilterApp({"status": "active", "name": "sw1"})
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FilterScreen)
        rm = screen.query_one("#rm-status", Button)
        screen.on_button_pressed(Button.Pressed(rm))
        await pilot.pause()
        assert screen.state.as_params() == {"name": "sw1"}
        assert screen.query_one("#f-status", Select).value is Select.NULL
        assert screen.query_one("#f-name", Input).value == "sw1"
        labels = {str(label.render()) for label in screen.query_one("#chips").query(Label)}
        assert labels == {"name = sw1"}


@pytest.mark.asyncio
async def test_clear_resyncs_common_widgets() -> None:
    app = _FilterApp({"status": "active", "name": "sw1"})
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FilterScreen)
        screen.action_clear()
        await pilot.pause()
        assert screen.state.as_params() == {}
        assert screen.query_one("#f-status", Select).value is Select.NULL
        assert screen.query_one("#f-name", Input).value == ""
        assert len(screen.query_one("#chips").children) == 0


@pytest.mark.asyncio
async def test_search_box_filters_and_clears() -> None:
    app = _FilterApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FilterScreen)
        search = screen.query_one("#search", Input)
        screen.on_input_changed(Input.Changed(search, "name"))
        await pilot.pause()
        results = screen.query_one("#search-results", ListView)
        labels = {str(item.query_one(Label).render()) for item in results.query(".search-result")}
        # case-insensitive substring: both `name` and `name__ic` surface
        assert labels == {"name", "name__ic"}
        screen.on_input_changed(Input.Changed(search, ""))
        await pilot.pause()
        assert len(results.children) == 0


@pytest.mark.asyncio
async def test_search_input_does_not_create_filter_key() -> None:
    app = _FilterApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FilterScreen)
        search = screen.query_one("#search", Input)
        screen.on_input_changed(Input.Changed(search, "name"))
        await pilot.pause()
        assert "search" not in screen.state.as_params()


@pytest.mark.asyncio
async def test_select_result_writes_into_raw_and_focuses() -> None:
    app = _FilterApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FilterScreen)
        search = screen.query_one("#search", Input)
        screen.on_input_changed(Input.Changed(search, "name__ic"))
        await pilot.pause()
        results = screen.query_one("#search-results", ListView)
        item = next(iter(results.query(".search-result")))
        screen.on_list_view_selected(ListView.Selected(results, item, 0))
        await pilot.pause()
        raw = screen.query_one("#raw", Input)
        assert raw.value == "name__ic="
        assert raw.has_focus


@pytest.mark.asyncio
async def test_select_changed_updates_and_clears_state() -> None:
    app = _FilterApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FilterScreen)
        select = screen.query_one("#f-status", Select)
        screen.on_select_changed(Select.Changed(select, "offline"))
        assert screen.state.as_params() == {"status": "offline"}
        screen.on_select_changed(Select.Changed(select, Select.NULL))
        assert screen.state.as_params() == {}


@pytest.mark.asyncio
async def test_input_changed_writes_field_into_state() -> None:
    app = _FilterApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FilterScreen)
        field = screen.query_one("#f-name", Input)
        screen.on_input_changed(Input.Changed(field, "sw1"))
        assert screen.state.as_params() == {"name": "sw1"}


@pytest.mark.asyncio
async def test_apply_and_clear_buttons_dispatch() -> None:
    app = _FilterApp({"status": "active"})
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, FilterScreen)
        clear = screen.query_one("#clear", Button)
        screen.on_button_pressed(Button.Pressed(clear))
        await pilot.pause()
        assert screen.state.as_params() == {}
        assert len(screen.query_one("#chips").children) == 0
        apply = screen.query_one("#apply", Button)
        screen.on_button_pressed(Button.Pressed(apply))
        await pilot.pause()
    assert app.result == {}
