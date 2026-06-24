"""GlobalSearchScreen — mimic the web-UI global search by fanning out ?q=.

There is no global-search REST endpoint, so an async worker queries a curated
set of common, q-capable resources one at a time (in a thread, so the UI stays
responsive) and streams matching records into a type-grouped tree. Selecting a
result opens its detail view.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Input, Label, Tree

from nsc.http.errors import NetBoxAPIError, NetBoxClientError
from nsc.model.command_model import CommandModel
from nsc.tui.catalog import ResourceRef
from nsc.tui.search import global_search_targets, search_target
from nsc.tui.widgets.nav_tree import NavTree

_HINT = "Enter search · ↓ results · ←/→ close/open · ⌃e all · Enter open · Esc close"
_PER_TYPE_LIMIT = 8
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def spinner_frame(index: int) -> str:
    """The braille spinner glyph for a given tick (cycles)."""
    return _SPINNER[index % len(_SPINNER)]


@dataclass(frozen=True)
class _Hit:
    ref: ResourceRef
    record: dict[str, Any]


def _record_label(record: dict[str, Any]) -> str:
    for key in ("display", "name", "address", "prefix", "slug"):
        value = record.get(key)
        if value:
            return str(value)
    return str(record.get("id", "?"))


class GlobalSearchScreen(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "dismiss", "Close"),
        ("down", "app.focus_next", "Down"),
        ("ctrl+e", "toggle_all", "Expand/collapse all"),
    ]

    def __init__(self, model: CommandModel, client: Any) -> None:
        super().__init__()
        self._model = model
        self._client = client
        self._targets = global_search_targets(model)
        self._spin_timer: Timer | None = None
        self._frame = 0
        self._target_name = ""
        self._pending_term = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="search-box"):
            yield Input(placeholder="Search NetBox…", id="search-input")
            yield Label("", id="search-status")
            tree = NavTree("results", id="search-tree")
            tree.show_root = False
            yield tree
            yield Label(_HINT, id="search-hint")

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "search-input":
            return
        term = event.value.strip()
        if term:
            self._pending_term = term
            # Pass the bound coroutine *function* (not a coroutine object) so an
            # exclusive cancel before the worker starts never leaves a coroutine
            # un-awaited.
            self.run_worker(self._run_pending, exclusive=True)  # type: ignore[arg-type]

    async def _run_pending(self) -> None:
        await self._run_search(self._pending_term)

    async def _run_search(self, term: str) -> None:
        tree = self.query_one("#search-tree", Tree)
        tree.clear()
        timer = self._begin_spinner()
        found = 0
        for ref in self._targets:
            self._target_name = ref.resource_name
            try:
                rows = await asyncio.to_thread(
                    search_target, self._client, ref, term, _PER_TYPE_LIMIT
                )
            except (NetBoxAPIError, NetBoxClientError):
                continue  # one bad endpoint must not abort the whole search
            if rows:
                self._add_group(ref, rows)
                found += len(rows)
        # Stop our own spinner only — never in a finally, so a superseded
        # (cancelled) worker can't stop the spinner a newer search just started.
        self._end_spinner(timer, found)

    def _begin_spinner(self) -> Timer:
        self._frame = 0
        self._target_name = ""
        timer = self.set_interval(0.1, self._tick)
        self._spin_timer = timer
        self._tick()
        return timer

    def _tick(self) -> None:
        self._frame += 1
        suffix = f" {self._target_name}" if self._target_name else ""
        self.query_one("#search-status", Label).update(
            f"{spinner_frame(self._frame)} Searching…{suffix}"
        )

    def _end_spinner(self, timer: Timer, found: int) -> None:
        timer.stop()
        # Only clear the shared handle if it is still ours; a newer search may
        # have already replaced it with its own running timer.
        if self._spin_timer is timer:
            self._spin_timer = None
        summary = f"{found} match{'es' if found != 1 else ''}" if found else "No matches."
        self.query_one("#search-status", Label).update(summary)

    def _add_group(self, ref: ResourceRef, rows: list[dict[str, Any]]) -> None:
        tree = self.query_one("#search-tree", Tree)
        group = tree.root.add(f"{ref.resource_name} ({len(rows)})", expand=True)
        for record in rows:
            group.add_leaf(_record_label(record), data=_Hit(ref, record))
        tree.cursor_line = max(tree.cursor_line, 0)

    def on_tree_node_selected(self, event: Tree.NodeSelected[Any]) -> None:
        hit = event.node.data
        if isinstance(hit, _Hit):
            self._open(hit)
        else:
            event.node.toggle()

    def _open(self, hit: _Hit) -> None:
        resource = self._model.tags[hit.ref.tag].resources[hit.ref.resource_name]
        from nsc.tui.screens.detail import DetailScreen  # noqa: PLC0415

        self.app.push_screen(
            DetailScreen(
                self._model,
                self._client,
                hit.ref.tag,
                hit.ref.resource_name,
                resource,
                hit.record,
            )
        )

    def action_toggle_all(self) -> None:
        tree = self.query_one("#search-tree", Tree)
        expand = not all(node.is_expanded for node in tree.root.children)
        for node in tree.root.children:
            if expand:
                node.expand()
            else:
                node.collapse()
