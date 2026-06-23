from __future__ import annotations

from textual.app import App, ComposeResult

from nsc.tui.forms import DiffRow
from nsc.tui.widgets.diff import DiffModal


class _DiffApp(App[None]):
    def __init__(self, rows: list[DiffRow]) -> None:
        super().__init__()
        self._rows = rows
        self.result: bool | None = None

    def compose(self) -> ComposeResult:
        yield from ()

    async def on_mount(self) -> None:
        def _store(value: bool) -> None:
            self.result = value

        await self.push_screen(DiffModal(self._rows), _store)


def _rows() -> list[DiffRow]:
    return [
        DiffRow(field="name", old_display="dev1", new_display="dev2"),
        DiffRow(field="token", old_display="****", new_display="****"),
    ]


def test_diff_modal_empty_rows_renders_no_changes() -> None:
    assert "No changes." in DiffModal([]).render_text()


async def test_diff_modal_renders_each_field_old_new() -> None:
    app = _DiffApp(_rows())
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DiffModal)
        text = screen.render_text()
        assert "name" in text
        assert "dev1" in text
        assert "dev2" in text


async def test_diff_modal_masks_sensitive_values() -> None:
    app = _DiffApp(_rows())
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DiffModal)
        text = screen.render_text()
        assert "token" in text
        assert "****" in text


async def test_diff_modal_confirm_dismisses_true() -> None:
    app = _DiffApp(_rows())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, DiffModal)
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, DiffModal)
        assert app.result is True


async def test_diff_modal_confirm_key_y_dismisses_true() -> None:
    app = _DiffApp(_rows())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert app.result is True


async def test_diff_modal_escape_dismisses_false() -> None:
    app = _DiffApp(_rows())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, DiffModal)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, DiffModal)
        assert app.result is False


async def test_diff_modal_cancel_key_n_dismisses_false() -> None:
    app = _DiffApp(_rows())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert app.result is False
