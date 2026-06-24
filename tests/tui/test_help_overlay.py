from __future__ import annotations

import io

from rich.console import Console
from textual.app import App, ComposeResult

from nsc.tui.widgets.help import HelpOverlay, help_renderable


def _rendered() -> str:
    """Plain-text projection of the overlay's renderable, for content assertions."""
    console = Console(file=io.StringIO(), width=120, no_color=True)
    console.print(help_renderable())
    return console.file.getvalue()


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
        text = _rendered()
        assert "Quit" in text
        assert "Filter" in text
        assert "Open related" in text
        assert "?" in text
        assert "/" in text
        assert "question_mark" not in text
        assert "slash" not in text
        await pilot.pause()


async def test_help_overlay_lists_edit_create_delete_descriptions() -> None:
    app = _HelpApp()
    async with app.run_test() as pilot:
        text = _rendered()
        assert "Create" in text
        assert "Edit" in text
        assert "Delete" in text
        await pilot.pause()


def _section_for(text: str, title: str) -> str:
    titles = ("Global", "List view", "Detail view", "Edit form")
    start = text.index(title)
    rest = text[start + len(title) :]
    ends = [rest.index(t) for t in titles if t in rest]
    return rest if not ends else rest[: min(ends)]


async def test_help_overlay_groups_edit_create_delete_under_their_context() -> None:
    """The overlay reads KEYMAP, so the edit/create/delete bindings land under
    the same context the keymap assigns and cannot drift from it."""
    app = _HelpApp()
    async with app.run_test() as pilot:
        text = _rendered()
        list_section = _section_for(text, "List view")
        detail_section = _section_for(text, "Detail view")
        assert "Create" in list_section
        assert "Edit" in detail_section
        assert "Delete" in detail_section
        assert "Create" not in detail_section
        assert "Edit" not in list_section
        assert "Delete" not in list_section
        await pilot.pause()
