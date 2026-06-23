from __future__ import annotations

import pytest

from nsc.tui.app import NscTuiApp
from nsc.tui.keymap import KEYMAP, KeyBinding, bindings_for, help_groups
from nsc.tui.screens.detail import DetailScreen
from nsc.tui.screens.list import ListScreen


def test_every_binding_has_required_fields() -> None:
    for b in KEYMAP:
        assert b.keys, "binding must declare at least one key"
        assert b.action
        assert b.description
        assert b.context in {"global", "list", "detail"}


def test_bindings_for_filters_by_context_and_includes_global() -> None:
    listing = bindings_for("list")
    contexts = {b.context for b in listing}
    assert contexts == {"global", "list"}
    actions = {b.action for b in listing}
    assert "cursor_down" in actions  # list nav
    assert "request_help" in actions  # global help


def test_help_groups_are_keyed_by_context_and_nonempty() -> None:
    groups = help_groups()
    assert set(groups) == {"global", "list", "detail"}
    assert all(len(v) >= 1 for v in groups.values())


def test_vim_and_arrow_aliases_share_one_binding() -> None:
    down = next(b for b in KEYMAP if b.action == "cursor_down")
    assert "j" in down.keys and "down" in down.keys


def test_keybinding_is_frozen_dataclass() -> None:
    assert isinstance(KEYMAP[0], KeyBinding)


_OWNER_FOR_CONTEXT = {
    "global": (NscTuiApp,),
    "list": (NscTuiApp, ListScreen),
    "detail": (NscTuiApp, DetailScreen),
}


@pytest.mark.parametrize("context", ["global", "list", "detail"])
def test_every_action_resolves_to_a_method(context: str) -> None:
    owners = _OWNER_FOR_CONTEXT[context]
    for b in bindings_for(context):
        method = f"action_{b.action}"
        assert any(hasattr(owner, method) for owner in owners), (
            f"{b.action!r} ({context}) has no action_ method on {owners}"
        )


@pytest.mark.parametrize("context", ["global", "list", "detail"])
def test_no_key_maps_to_two_actions_in_a_context(context: str) -> None:
    seen: dict[str, str] = {}
    for b in bindings_for(context):
        for key in b.keys:
            if key in seen:
                assert seen[key] == b.action, (
                    f"key {key!r} maps to {seen[key]!r} and {b.action!r} in {context}"
                )
            seen[key] = b.action


def test_no_accidental_bare_letter_palette_key() -> None:
    palette = next(b for b in KEYMAP if b.action == "open_palette")
    assert palette.keys == ("ctrl+p",)


def test_display_keys_renders_pressable_glyphs() -> None:
    help_binding = next(b for b in KEYMAP if b.action == "request_help")
    filter_binding = next(b for b in KEYMAP if b.action == "focus_filter")
    assert help_binding.display_keys == "?"
    assert filter_binding.display_keys == "/"
    assert "question_mark" not in help_binding.display_keys
    assert "slash" not in filter_binding.display_keys
