from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Label, Static, Tree

from nsc.http.errors import NetBoxAPIError
from nsc.model.command_model import (
    CommandModel,
    Operation,
    Parameter,
    ParameterLocation,
    Resource,
    Tag,
)
from nsc.tui.screens.detail import DetailScreen
from nsc.tui.screens.global_search import GlobalSearchScreen, spinner_frame


def _q_list(path: str) -> Operation:
    return Operation(
        operation_id=path,
        http_method="GET",
        path=path,
        parameters=[Parameter(name="q", location=ParameterLocation.QUERY)],
    )


def _model() -> CommandModel:
    dcim = Tag(
        name="dcim",
        resources={
            "devices": Resource(
                name="devices",
                list_op=_q_list("/api/dcim/devices/"),
                get_op=Operation(
                    operation_id="g", http_method="GET", path="/api/dcim/devices/{id}/"
                ),
            )
        },
    )
    ipam = Tag(
        name="ipam",
        resources={"prefixes": Resource(name="prefixes", list_op=_q_list("/api/ipam/prefixes/"))},
    )
    return CommandModel(
        info_title="t", info_version="1", schema_hash="h", tags={"dcim": dcim, "ipam": ipam}
    )


class _Client:
    """Returns a hit for devices, nothing for prefixes, raising for none."""

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any:
        if "devices" in path:
            yield {"id": 7, "name": "sw1"}
        # prefixes yields nothing


class _SearchApp(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.client = _Client()

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        await self.push_screen(GlobalSearchScreen(_model(), self.client))


def _screen(app: _SearchApp) -> GlobalSearchScreen:
    screen = app.screen
    assert isinstance(screen, GlobalSearchScreen)
    return screen


@pytest.mark.asyncio
async def test_search_groups_matches_by_type_and_omits_empty_groups() -> None:
    app = _SearchApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _screen(app)
        await screen._run_search("sw")
        await pilot.pause()
        tree = screen.query_one("#search-tree", Tree)
        labels = [str(node.label) for node in tree.root.children]
        # devices matched (count shown); prefixes had no hits and is omitted
        assert labels == ["devices (1)"]


def test_spinner_frame_cycles() -> None:
    assert spinner_frame(0) == spinner_frame(10)  # 10 frames, wraps
    assert spinner_frame(0) != spinner_frame(1)
    assert all(spinner_frame(i) for i in range(25))  # never empty


@pytest.mark.asyncio
async def test_status_shows_match_count_after_search() -> None:
    app = _SearchApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _screen(app)
        await screen._run_search("sw")  # devices yields one hit
        await pilot.pause()
        status = str(screen.query_one("#search-status", Label).render())
        assert status == "1 match"
        # spinner timer is stopped after the search ends
        assert screen._spin_timer is None


@pytest.mark.asyncio
async def test_status_shows_no_matches_when_empty() -> None:
    class _EmptyClient:
        def paginate(self, path, params=None, *, limit=None):  # type: ignore[no-untyped-def]
            return iter([])

    app = _SearchApp()
    app.client = _EmptyClient()  # type: ignore[assignment]
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen._client = app.client
        await screen._run_search("zzz")
        await pilot.pause()
        assert str(screen.query_one("#search-status", Label).render()) == "No matches."


@pytest.mark.asyncio
async def test_selecting_a_hit_opens_its_detail() -> None:
    app = _SearchApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _screen(app)
        await screen._run_search("sw")
        await pilot.pause()
        tree = screen.query_one("#search-tree", Tree)
        leaf = tree.root.children[0].children[0]
        screen.on_tree_node_selected(Tree.NodeSelected(leaf))
        await pilot.pause()
        pushed = app.screen
        assert isinstance(pushed, DetailScreen)
        assert pushed._resource_name == "devices"
        assert pushed._record == {"id": 7, "name": "sw1"}


class _FlakyClient:
    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any:
        if "prefixes" in path:
            raise NetBoxAPIError(status_code=500, url=path, body_snippet="boom", headers={})
        yield {"id": 7, "name": "sw1"}


class _FlakyApp(_SearchApp):
    def __init__(self) -> None:
        super().__init__()
        self.client = _FlakyClient()


@pytest.mark.asyncio
async def test_submitting_input_runs_worker_and_populates_tree() -> None:
    app = _SearchApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _screen(app)
        screen.query_one("#search-input").focus()
        await pilot.pause()
        await pilot.press(*"sw")
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        tree = screen.query_one("#search-tree", Tree)
        assert [str(n.label) for n in tree.root.children] == ["devices (1)"]
        # The exclusive worker finished and left no dangling spinner timer.
        assert screen._spin_timer is None


@pytest.mark.asyncio
async def test_a_failing_target_is_skipped_not_fatal() -> None:
    app = _FlakyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _screen(app)
        await screen._run_search("sw")  # prefixes raises; devices still shown
        await pilot.pause()
        tree = screen.query_one("#search-tree", Tree)
        assert [str(n.label) for n in tree.root.children] == ["devices (1)"]
