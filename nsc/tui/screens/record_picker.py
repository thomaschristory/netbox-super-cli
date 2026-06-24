"""RecordPicker — searchable list of records for a foreign-key target endpoint."""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar, Protocol

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Input, Label, ListItem, ListView

from nsc.http.errors import NetBoxAPIError, NetBoxClientError
from nsc.model.command_model import Operation
from nsc.tui.errors import api_error_message

_PAGE_LIMIT = 50
_DEBOUNCE = 0.25


class _Client(Protocol):
    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any: ...


def _label(record: dict[str, Any]) -> str:
    display = record.get("display")
    return str(display) if display is not None else str(record.get("id", ""))


class RecordPicker(ModalScreen[tuple[int, str]]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "dismiss", "Close"),
        # Down from the search box drops into the list; the list then owns down.
        ("down", "app.focus_next", "Down"),
    ]

    def __init__(self, client: _Client, list_op: Operation, current_id: int | None = None) -> None:
        super().__init__()
        self._client = client
        self._op = list_op
        self._current_id = current_id
        self._pending = ""
        self._debounce: Timer | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="record-picker"):
            yield Input(placeholder="Search…", id="record-picker-filter")
            yield ListView(id="record-picker-list")

    def on_mount(self) -> None:
        self._launch_query()
        self.query_one("#record-picker-filter", Input).focus()

    def _launch_query(self) -> None:
        # Pass a coroutine *function* (not a coroutine object) so an exclusive cancel
        # before the worker starts never leaves a coroutine un-awaited.
        self.run_worker(self._run_pending, group="pick", exclusive=True)  # type: ignore[arg-type]

    async def _run_pending(self) -> None:
        await self._query(self._pending)

    async def _query(self, search: str) -> None:
        listing = self.query_one("#record-picker-list", ListView)
        listing.loading = True
        try:
            params = {"q": search} if search else None
            records = await asyncio.to_thread(
                lambda: list(self._client.paginate(self._op.path, params, limit=_PAGE_LIMIT))
            )
            await self._populate(records)
        except (NetBoxAPIError, NetBoxClientError) as exc:
            self.notify(api_error_message(exc), severity="error", timeout=8)
            await self._populate([])
        finally:
            listing.loading = False

    async def _populate(self, records: list[dict[str, Any]]) -> None:
        lv = self.query_one("#record-picker-list", ListView)
        # Await the clear so appends below land on an empty list, not a deferred-clear race.
        await lv.clear()
        highlight = 0
        for idx, record in enumerate(records):
            item = ListItem(Label(_label(record)))
            item.data = record  # type: ignore[attr-defined]
            lv.append(item)
            if self._current_id is not None and record.get("id") == self._current_id:
                highlight = idx
        if records:
            lv.index = highlight

    def on_input_changed(self, event: Input.Changed) -> None:
        self._pending = event.value
        if self._debounce is not None:
            self._debounce.stop()
        self._debounce = self.set_timer(_DEBOUNCE, self._launch_query)

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self._dismiss_with(self.query_one("#record-picker-list", ListView).highlighted_child)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self._dismiss_with(event.item)

    def _dismiss_with(self, item: ListItem | None) -> None:
        record = getattr(item, "data", None)
        if isinstance(record, dict):
            record_id = record.get("id")
            if isinstance(record_id, int):
                self.dismiss((record_id, _label(record)))
