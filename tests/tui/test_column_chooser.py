from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Label, ListView, Static

from nsc.tui.screens.columns import ColumnChooserScreen


class _ChooserApp(App[None]):
    def __init__(
        self,
        available: list[str],
        visible: list[str],
        labels: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.result: list[str] | None = None
        self._sentinel = object()
        self._available = available
        self._visible = visible
        self._chooser_labels = labels

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        def _cb(cols: list[str] | None) -> None:
            self.result = cols

        await self.push_screen(
            ColumnChooserScreen(self._available, self._visible, labels=self._chooser_labels), _cb
        )


def _chooser(app: _ChooserApp) -> ColumnChooserScreen:
    screen = app.screen
    assert isinstance(screen, ColumnChooserScreen)
    return screen


@pytest.mark.asyncio
async def test_toggle_then_apply_returns_visible_in_order() -> None:
    app = _ChooserApp(available=["id", "name", "status"], visible=["id", "name"])
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _chooser(app)
        screen.action_toggle_column()  # cursor on "id" (index 0) -> hide it
        screen.action_apply()
        await pilot.pause()
    assert app.result == ["name"]


@pytest.mark.asyncio
async def test_show_hidden_column_via_toggle() -> None:
    app = _ChooserApp(available=["id", "name", "status"], visible=["id"])
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _chooser(app)
        # items order: ["id", "name", "status"]; move cursor to "status" and show it
        listing = screen.query_one("#columns-list")
        listing.index = 2
        screen.action_toggle_column()
        screen.action_apply()
        await pilot.pause()
    assert app.result == ["id", "status"]


@pytest.mark.asyncio
async def test_reorder_then_apply() -> None:
    app = _ChooserApp(available=["a", "b", "c"], visible=["a", "b", "c"])
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _chooser(app)
        listing = screen.query_one("#columns-list")
        listing.index = 0  # on "a"
        screen.action_move_down()  # a -> position 1
        screen.action_apply()
        await pilot.pause()
    assert app.result == ["b", "a", "c"]


@pytest.mark.asyncio
async def test_enter_key_applies() -> None:
    # The ListView owns enter; the screen must still apply on it.
    app = _ChooserApp(available=["id", "name", "status"], visible=["id", "name"])
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert app.result == ["id", "name"]


@pytest.mark.asyncio
async def test_space_key_toggles_then_enter_applies() -> None:
    app = _ChooserApp(available=["id", "name", "status"], visible=["id", "name"])
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("space")  # cursor on "id" -> hide it
        await pilot.press("enter")
        await pilot.pause()
    assert app.result == ["name"]


@pytest.mark.asyncio
async def test_escape_cancels_with_none() -> None:
    app = _ChooserApp(available=["id", "name"], visible=["id"])
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None


@pytest.mark.asyncio
async def test_empty_selection_is_not_applied() -> None:
    app = _ChooserApp(available=["id"], visible=["id"])
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _chooser(app)
        screen.action_toggle_column()  # hide the only visible column
        screen.action_apply()  # should refuse (empty)
        await pilot.pause()
        assert isinstance(app.screen, ColumnChooserScreen)  # still open
    assert app.result is None


@pytest.mark.asyncio
async def test_chooser_renders_labels_but_applies_raw_keys() -> None:
    app = _ChooserApp(
        available=["name", "custom_fields.rack_role"],
        visible=["name", "custom_fields.rack_role"],
        labels={"name": "name", "custom_fields.rack_role": "Rack Role"},
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _chooser(app)
        shown = [label.render().plain for label in screen.query(ListView).first().query(Label)]
        assert any("Rack Role" in s for s in shown)
        assert not any("custom_fields.rack_role" in s for s in shown)
        screen.action_apply()
        await pilot.pause()
    # The applied/visible columns keep the raw selector key, not the label.
    assert app.result == ["name", "custom_fields.rack_role"]
