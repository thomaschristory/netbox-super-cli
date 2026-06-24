"""Pure, Textual-free model for the column chooser.

``available_columns`` lists every field the loaded records expose; a
``ColumnSelection`` holds an ordered list of those fields with a visible/hidden
flag each, plus reorder operations. The screen renders this and reads back
``visible_in_order``.
"""

from __future__ import annotations

from typing import Any

from nsc.output.flatten import flatten


def available_columns(records: list[dict[str, Any]]) -> list[str]:
    """Ordered union of the flattened keys across ``records`` (first-seen order)."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for record in records:
        for key in flatten(record):
            if key not in seen_set:
                seen_set.add(key)
                seen.append(key)
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
