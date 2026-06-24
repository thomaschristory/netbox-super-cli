"""Fuzzy resource picker — landing screen and ``ctrl+p`` jump target.

Resources are shown as a tree grouped by tag (super-group): tags collapse and
expand, arrows browse and open/close groups, and the search bar hides
non-matching groups while auto-expanding the rest.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Tree

from nsc.model.command_model import CommandModel
from nsc.tui.catalog import ResourceRef, filter_resources, group_refs, list_resources
from nsc.tui.nav import can_go_back
from nsc.tui.widgets.nav_tree import NavTree

_HINT = "↓ list · ←/→ close/open · ⌃e all · ⌃f search · Enter pick · Esc close"


class ResourcePicker(ModalScreen[ResourceRef]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "cancel", "Close"),
        # Down from the search box drops into the tree; the tree then owns down.
        ("down", "app.focus_next", "Down"),
        ("ctrl+e", "toggle_all", "Expand/collapse all"),
        # Reach global search from the landing picker (app.* routes to the App,
        # which holds the client the search needs).
        ("ctrl+f", "app.open_search", "Search"),
    ]

    def __init__(self, model: CommandModel) -> None:
        super().__init__()
        self._refs = list_resources(model)
        self._filtered = list(self._refs)
        self._expanded_all = False

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Input(placeholder="Filter resources…", id="picker-filter")
            tree = NavTree("resources", id="picker-tree")
            tree.show_root = False
            yield tree
            yield Label(_HINT, id="picker-hint")

    def on_mount(self) -> None:
        self._build(group_refs(self._refs), expand=False)
        self.query_one("#picker-filter", Input).focus()

    def _build(self, groups: list[tuple[str, list[ResourceRef]]], *, expand: bool) -> None:
        tree = self.query_one("#picker-tree", Tree)
        tree.clear()
        for tag, refs in groups:
            node = tree.root.add(tag, expand=expand)
            for ref in refs:
                node.add_leaf(ref.resource_name, data=ref)
        # Place the cursor on the first node so left/right act immediately once
        # the tree is focused (Textual leaves cursor_line at -1 otherwise).
        if tree.root.children:
            tree.cursor_line = 0
        self._expanded_all = expand

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "picker-filter":
            return
        query = event.value.strip()
        self._filtered = filter_resources(self._refs, query)
        # Querying hides non-matching groups and expands the matches; an empty
        # query shows every group, collapsed.
        self._build(group_refs(self._filtered), expand=bool(query))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "picker-filter" and self._filtered:
            self.dismiss(self._filtered[0])

    def on_tree_node_selected(self, event: Tree.NodeSelected[ResourceRef]) -> None:
        ref = event.node.data
        if isinstance(ref, ResourceRef):
            self.dismiss(ref)
        else:
            event.node.toggle()

    def action_toggle_all(self) -> None:
        self._expanded_all = not self._expanded_all
        for node in self.query_one("#picker-tree", Tree).root.children:
            if self._expanded_all:
                node.expand()
            else:
                node.collapse()

    def action_cancel(self) -> None:
        # As the landing screen there is nothing beneath but the blank base, so
        # closing would black out; stay put and hint instead.
        if can_go_back(self.app):
            self.dismiss()
        else:
            self.notify("Press q to quit, or pick a resource to continue.")
