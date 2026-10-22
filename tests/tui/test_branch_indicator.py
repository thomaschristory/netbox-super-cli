from __future__ import annotations

import pytest

from nsc.tui.app import NscTuiApp
from tests.tui.test_app import _FakeClient, _model


@pytest.mark.asyncio
async def test_title_shows_branch() -> None:
    app = NscTuiApp(_model(), _FakeClient(), branch="my-change")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.title == "nsc ⎇ my-change"
        assert app.has_class("-branch")


@pytest.mark.asyncio
async def test_title_plain_without_branch() -> None:
    app = NscTuiApp(_model(), _FakeClient())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.title == "nsc"
        assert not app.has_class("-branch")
