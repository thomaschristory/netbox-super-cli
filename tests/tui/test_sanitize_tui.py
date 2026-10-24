"""TUI cells and messages don't render server text as markup or control codes (#206)."""

from __future__ import annotations

from typing import Any

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Label, ListView, Static

from nsc.http.errors import NetBoxAPIError
from nsc.output.colors import ColoredValue
from nsc.tui.errors import api_error_message
from nsc.tui.screens.detail import DetailScreen
from nsc.tui.view import render_cell
from tests.tui.test_detail_screen import _model, _SpyClient
from tests.tui.test_record_picker import _FakeClient, _PickerApp

EVIL = "[bold red]x[/] \x1b]0;pwned\x07"
SHOWN = "[bold red]x[/] \\x1b]0;pwned\\x07"


def _plain(cell: object) -> str:
    # A plain `str` would be parsed as markup by DataTable/Label; Textual's own
    # `Content` (from Label.render) is already literal.
    assert not isinstance(cell, str), cell
    return str(cell.plain)  # type: ignore[attr-defined]


def test_render_cell_returns_sanitized_text_not_markup() -> None:
    assert _plain(render_cell(EVIL)) == SHOWN
    assert _plain(render_cell(ColoredValue(text=EVIL, color="ff0000"))) == SHOWN
    assert render_cell(None) == ""


def test_api_error_message_is_safe_for_markup_notifications() -> None:
    exc = NetBoxAPIError(status_code=500, url="https://nb/api/x/", body_snippet=EVIL, headers={})
    message = api_error_message(exc)
    assert "\x1b" not in message
    assert Text.from_markup(message).plain == f"API 500 — {SHOWN}"


class _EvilDetailApp(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.client = _SpyClient()

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        model = _model()
        resource = model.tags["dcim"].resources["devices"]
        record: dict[str, Any] = {"id": 7, "name": EVIL, f"k{EVIL}": EVIL}
        screen = DetailScreen(model, self.client, "dcim", "devices", resource, record)
        await self.push_screen(screen)


@pytest.mark.asyncio
async def test_detail_cells_are_sanitized_text() -> None:
    app = _EvilDetailApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.screen.query_one("#fields", DataTable)
        rows = [table.get_row_at(i) for i in range(table.row_count)]
        cells = {_plain(label): _plain(value) for label, value in rows}
        assert cells["name"] == SHOWN
        assert cells[f"k{SHOWN}"] == SHOWN


@pytest.mark.asyncio
async def test_record_picker_labels_are_sanitized_text() -> None:
    app = _PickerApp(_FakeClient([{"id": 1, "display": EVIL}]))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        label = app.screen.query_one(ListView).query_one(Label)
        assert _plain(label.render()) == SHOWN
