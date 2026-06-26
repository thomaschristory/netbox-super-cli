"""Pure, Textual-free model for the column chooser.

``available_columns`` lists every selectable field the loaded records expose
(custom fields individually, as ``custom_fields.<name>``); a
``ColumnSelection`` holds an ordered list of those fields with a visible/hidden
flag each, plus reorder operations. The screen renders this and reads back
``visible_in_order``.
"""

from __future__ import annotations

from typing import Any


def available_columns(records: list[dict[str, Any]]) -> list[str]:
    """Ordered union of the records' selectable columns (first-seen order).

    Only top-level fields are offered, with one deliberate exception:
    ``custom_fields``. A foreign key or choice object stays one column (the
    table renders it via its ``display``/``label``), so the chooser shows
    ``site`` rather than ``site.id`` / ``site.url`` / ``site.display``. But
    ``custom_fields`` holds user-defined values worth their own column each, so
    it is expanded into ``custom_fields.<name>`` entries (first-seen union of
    the inner keys) rather than a single opaque JSON column. Records whose
    ``custom_fields`` is absent, empty, or not a dict contribute no such column.
    """
    seen: list[str] = []
    seen_set: set[str] = set()

    def _add(key: str) -> None:
        if key not in seen_set:
            seen_set.add(key)
            seen.append(key)

    for record in records:
        for key, value in record.items():
            if key == "custom_fields" and isinstance(value, dict):
                for name in value:
                    _add(f"custom_fields.{name}")
            else:
                _add(key)
    return seen


class ColumnSelection:
    """Ordered columns with per-column visibility and edge-clamped reordering."""

    def __init__(self, available: list[str], visible: list[str]) -> None:
        # Visible columns first (in their order, even if not in `available`),
        # then the remaining available columns in their natural order.
        self.items: list[str] = list(dict.fromkeys([*visible, *available]))
        self._visible: set[str] = set(visible)

    def is_visible(self, name: str) -> bool:
        return name in self._visible

    def toggle(self, name: str) -> None:
        if name in self._visible:
            self._visible.discard(name)
        else:
            self._visible.add(name)

    def move_up(self, index: int) -> int:
        if 0 < index < len(self.items):
            self.items[index - 1], self.items[index] = self.items[index], self.items[index - 1]
            return index - 1
        return index

    def move_down(self, index: int) -> int:
        if 0 <= index < len(self.items) - 1:
            self.items[index + 1], self.items[index] = self.items[index], self.items[index + 1]
            return index + 1
        return index

    def visible_in_order(self) -> list[str]:
        return [name for name in self.items if name in self._visible]
