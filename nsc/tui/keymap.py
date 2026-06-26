"""The single source of truth for TUI keybindings.

Footer, help overlay, and Textual ``BINDINGS`` all derive from ``KEYMAP``, so
they cannot drift apart. This module imports nothing from Textual.
"""

from __future__ import annotations

from dataclasses import dataclass

Context = str  # "global" | "list" | "detail" | "edit" | "bulk" | "filter"

# Textual key identifiers have no printable form; map them to the glyph the
# user actually presses so footer and help do not show raw tokens.
_KEY_GLYPHS = {
    "question_mark": "?",
    "slash": "/",
    "escape": "Esc",
    "backspace": "⌫",
}


@dataclass(frozen=True)
class KeyBinding:
    keys: tuple[str, ...]
    action: str
    description: str
    context: Context
    show: bool = True

    @property
    def display_keys(self) -> str:
        return " / ".join(_KEY_GLYPHS.get(k, k) for k in self.keys)


def _b(keys: str, action: str, description: str, context: Context, show: bool = True) -> KeyBinding:
    return KeyBinding(tuple(keys.split()), action, description, context, show)


KEYMAP: tuple[KeyBinding, ...] = (
    _b("q", "quit_tui", "Quit", "global"),
    _b("question_mark", "request_help", "Help", "global"),
    _b("ctrl+p", "open_palette", "Find resource", "global"),
    _b("ctrl+f", "open_search", "Search", "global"),
    _b("escape", "go_back", "Back", "global"),
    _b("j down", "cursor_down", "Down", "list"),
    _b("k up", "cursor_up", "Up", "list"),
    _b("g", "cursor_top", "Top", "list"),
    _b("G", "cursor_bottom", "Bottom", "list"),
    _b("enter", "open_detail", "Open", "list"),
    _b("slash", "open_filters", "Filter", "list"),
    _b("r", "refresh_list", "Refresh", "list"),
    _b("v space", "toggle_select", "Select", "list"),
    _b("c", "create_record", "Create", "list"),
    _b("f", "edit_columns", "Fields", "list"),
    _b("B", "bulk_edit", "Bulk edit", "list"),
    _b("b", "go_back", "Back", "detail"),
    _b("tab", "next_tab", "Next tab", "detail"),
    _b("shift+tab", "prev_tab", "Prev tab", "detail"),
    _b("enter e", "edit_field", "Edit field", "detail"),
    _b("s", "save_all", "Save changes", "detail"),
    _b("o", "drill_relation", "Open related", "detail"),
    _b("d", "delete_record", "Delete", "detail"),
    _b("s", "save", "Save", "edit"),
    _b("b", "go_back", "Back", "edit"),
    _b("p", "preview", "Preview changes", "bulk"),
    _b("b", "go_back", "Back", "bulk"),
    _b("ctrl+s", "apply", "Apply", "filter"),
    _b("ctrl+w", "save_search", "Save search", "filter"),
    _b("ctrl+o", "load_search", "Load saved", "filter"),
)


def bindings_for(context: Context) -> list[KeyBinding]:
    """Bindings active in ``context``, including all global bindings."""
    return [b for b in KEYMAP if b.context in ("global", context)]


def help_groups() -> dict[Context, list[KeyBinding]]:
    """All bindings grouped by context, for the help overlay."""
    groups: dict[Context, list[KeyBinding]] = {
        "global": [],
        "list": [],
        "detail": [],
        "edit": [],
        "bulk": [],
        "filter": [],
    }
    for b in KEYMAP:
        groups[b.context].append(b)
    return groups
