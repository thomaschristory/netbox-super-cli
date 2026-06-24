"""A pure, framework-free buffer of selected record ids.

Backs multi-select on the ListScreen. Order preservation matters: bulk
operations replay against records in the order the user picked them, so this is
built on an insertion-ordered ``dict`` rather than a ``set``. Imports nothing
from Textual.
"""

from __future__ import annotations

Id = int | str


class Selection:
    def __init__(self) -> None:
        self._ids: dict[Id, None] = {}

    def toggle(self, id_: Id) -> None:
        if id_ in self._ids:
            del self._ids[id_]
        else:
            self._ids[id_] = None

    def contains(self, id_: Id) -> bool:
        return id_ in self._ids

    def ids(self) -> tuple[Id, ...]:
        return tuple(self._ids)

    def clear(self) -> None:
        self._ids.clear()

    def __len__(self) -> int:
        return len(self._ids)

    def __bool__(self) -> bool:
        return bool(self._ids)
