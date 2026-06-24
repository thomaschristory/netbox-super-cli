from __future__ import annotations

import pytest

from nsc.tui.app import NscTuiApp
from nsc.tui.keymap import KEYMAP, KeyBinding, bindings_for, help_groups
from nsc.tui.screens.detail import DetailScreen
from nsc.tui.screens.edit_form import EditForm
from nsc.tui.screens.list import ListScreen


def test_every_binding_has_required_fields() -> None:
    for b in KEYMAP:
        assert b.keys, "binding must declare at least one key"
        assert b.action
        assert b.description
        assert b.context in {"global", "list", "detail", "edit"}


def test_bindings_for_filters_by_context_and_includes_global() -> None:
    listing = bindings_for("list")
    contexts = {b.context for b in listing}
    assert contexts == {"global", "list"}
    actions = {b.action for b in listing}
    assert "cursor_down" in actions  # list nav
    assert "request_help" in actions  # global help


def test_help_groups_are_keyed_by_context_and_nonempty() -> None:
    groups = help_groups()
    assert set(groups) == {"global", "list", "detail", "edit"}
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
    "edit": (NscTuiApp, EditForm),
}


@pytest.mark.parametrize("context", ["global", "list", "detail", "edit"])
def test_every_action_resolves_to_a_method(context: str) -> None:
    owners = _OWNER_FOR_CONTEXT[context]
    for b in bindings_for(context):
        method = f"action_{b.action}"
        assert any(hasattr(owner, method) for owner in owners), (
            f"{b.action!r} ({context}) has no action_ method on {owners}"
        )


@pytest.mark.parametrize("context", ["global", "list", "detail", "edit"])
def test_no_key_maps_to_two_actions_in_a_context(context: str) -> None:
    seen: dict[str, str] = {}
    for b in bindings_for(context):
        for key in b.keys:
            if key in seen:
                assert seen[key] == b.action, (
                    f"key {key!r} maps to {seen[key]!r} and {b.action!r} in {context}"
                )
            seen[key] = b.action


def test_edit_record_is_a_detail_binding_on_e() -> None:
    edit = next(b for b in KEYMAP if b.action == "edit_record")
    assert edit.context == "detail"
    assert edit.keys == ("e",)


def test_create_record_is_a_list_binding_on_a_or_c() -> None:
    create = next(b for b in KEYMAP if b.action == "create_record")
    assert create.context == "list"
    assert create.keys in (("a",), ("c",))


def test_delete_record_is_a_detail_binding_on_d() -> None:
    delete = next(b for b in KEYMAP if b.action == "delete_record")
    assert delete.context == "detail"
    assert delete.keys == ("d",)


def test_no_accidental_bare_letter_palette_key() -> None:
    palette = next(b for b in KEYMAP if b.action == "open_palette")
    assert palette.keys == ("ctrl+p",)


def test_help_groups_place_edit_create_delete_in_their_contexts() -> None:
    groups = help_groups()
    list_actions = {b.action for b in groups["list"]}
    detail_actions = {b.action for b in groups["detail"]}
    assert "create_record" in list_actions
    assert "edit_record" in detail_actions
    assert "delete_record" in detail_actions
    assert "edit_record" not in list_actions
    assert "delete_record" not in list_actions
    assert "create_record" not in detail_actions


def test_list_footer_bindings_surface_create() -> None:
    actions = {b.action for b in bindings_for("list")}
    assert "create_record" in actions


def test_detail_footer_bindings_surface_edit_and_delete() -> None:
    actions = {b.action for b in bindings_for("detail")}
    assert "edit_record" in actions
    assert "delete_record" in actions


def test_edit_context_has_no_dead_detail_keys() -> None:
    edit_actions = {b.action for b in bindings_for("edit")}
    for dead in ("edit_record", "delete_record", "drill_relation", "next_tab", "prev_tab"):
        assert dead not in edit_actions
    assert "save" in edit_actions
    assert "go_back" in edit_actions


def test_toggle_select_is_a_list_binding_on_v_and_space() -> None:
    toggle = next(b for b in KEYMAP if b.action == "toggle_select")
    assert toggle.context == "list"
    assert "v" in toggle.keys
    assert "space" in toggle.keys


def test_toggle_select_surfaces_in_list_bindings_and_help() -> None:
    list_actions = {b.action for b in bindings_for("list")}
    assert "toggle_select" in list_actions
    help_list_actions = {b.action for b in help_groups()["list"]}
    assert "toggle_select" in help_list_actions


def test_bulk_edit_action_not_required_yet() -> None:
    assert all(b.action != "bulk_edit" for b in KEYMAP)


def test_display_keys_renders_pressable_glyphs() -> None:
    help_binding = next(b for b in KEYMAP if b.action == "request_help")
    filter_binding = next(b for b in KEYMAP if b.action == "focus_filter")
    assert help_binding.display_keys == "?"
    assert filter_binding.display_keys == "/"
    assert "question_mark" not in help_binding.display_keys
    assert "slash" not in filter_binding.display_keys
