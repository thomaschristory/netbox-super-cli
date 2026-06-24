"""A Tree where the left/right arrows collapse/expand the cursor node.

Textual's ``Tree`` toggles on space/enter and leaves left/right unbound; this
adds the arrow behaviour most TUIs expect. Shared by the resource picker and
the global-search results.
"""

from __future__ import annotations

from typing import Any, ClassVar

from textual.binding import Binding, BindingType
from textual.widgets import Tree


class NavTree(Tree[Any]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("right", "expand_node", "Open", show=False),
        Binding("left", "collapse_or_parent", "Close", show=False),
    ]

    def action_expand_node(self) -> None:
        node = self.cursor_node
        if node is not None and node.allow_expand and not node.is_expanded:
            node.expand()

    def action_collapse_or_parent(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.allow_expand and node.is_expanded:
            node.collapse()
        elif node.parent is not None and node.parent is not self.root:
            self.action_cursor_parent()
