from __future__ import annotations

from textual.app import App, ComposeResult

from nsc.tui.widgets.help import HelpOverlay


class _HelpApp(App[None]):
    def compose(self) -> ComposeResult:
        yield HelpOverlay()


class _PushHelpApp(App[None]):
    def compose(self) -> ComposeResult:
        yield from ()

    async def on_mount(self) -> None:
        await self.push_screen(HelpOverlay())


async def test_help_overlay_stays_open_on_scroll_key() -> None:
    app = _PushHelpApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, HelpOverlay)
        await pilot.press("down")
        await pilot.pause()
        assert isinstance(app.screen, HelpOverlay)


async def test_help_overlay_closes_on_q() -> None:
    app = _PushHelpApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, HelpOverlay)
        await pilot.press("q")
        await pilot.pause()
        assert not isinstance(app.screen, HelpOverlay)


async def test_help_overlay_lists_every_action_description() -> None:
    app = _HelpApp()
    async with app.run_test() as pilot:
        text = app.screen.query_one(HelpOverlay).render_text()
        assert "Quit" in text
        assert "Filter" in text
        assert "Open related" in text
        assert "?" in text
        assert "/" in text
        assert "question_mark" not in text
        assert "slash" not in text
        await pilot.pause()
