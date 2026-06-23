from __future__ import annotations

from textual.app import App, ComposeResult

from nsc.tui.widgets.help import HelpOverlay


class _HelpApp(App[None]):
    def compose(self) -> ComposeResult:
        yield HelpOverlay()


async def test_help_overlay_lists_every_action_description() -> None:
    app = _HelpApp()
    async with app.run_test() as pilot:
        text = app.screen.query_one(HelpOverlay).render_text()
        assert "Quit" in text
        assert "Filter" in text
        assert "Open related" in text
        await pilot.pause()
