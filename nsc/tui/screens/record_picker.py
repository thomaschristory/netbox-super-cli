"""RecordPicker — searchable list of records for a foreign-key target endpoint."""

from __future__ import annotations

from typing import Any, ClassVar, Protocol

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView

from nsc.model.command_model import Operation

_PAGE_LIMIT = 50


class _Client(Protocol):
    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any: ...


def _label(record: dict[str, Any]) -> str:
    display = record.get("display")
    return str(display) if display is not None else str(record.get("id", ""))


class RecordPicker(ModalScreen[tuple[int, str]]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "dismiss", "Close")]

    def __init__(self, client: _Client, list_op: Operation, current_id: int | None = None) -> None:
        super().__init__()
        self._client = client
        self._op = list_op
        self._current_id = current_id

    def compose(self) -> ComposeResult:
        with Vertical(id="record-picker"):
            yield Input(placeholder="Search…", id="record-picker-filter")
            yield ListView(id="record-picker-list")

    def on_mount(self) -> None:
        self._query("")
        self.query_one("#record-picker-filter", Input).focus()

    def _query(self, search: str) -> None:
        params = {"q": search} if search else None
        records = list(self._client.paginate(self._op.path, params, limit=_PAGE_LIMIT))
        self._populate(records)

    def _populate(self, records: list[dict[str, Any]]) -> None:
        lv = self.query_one("#record-picker-list", ListView)
        lv.clear()
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
        self._query(event.value)

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
