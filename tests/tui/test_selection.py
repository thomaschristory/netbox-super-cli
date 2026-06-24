from __future__ import annotations

import importlib
import inspect

from nsc.tui.selection import Selection


def test_starts_empty() -> None:
    sel: Selection = Selection()
    assert len(sel) == 0
    assert not sel
    assert sel.ids() == ()


def test_toggle_adds_then_removes() -> None:
    sel: Selection = Selection()
    sel.toggle(1)
    assert sel.contains(1)
    assert len(sel) == 1
    sel.toggle(1)
    assert not sel.contains(1)
    assert len(sel) == 0


def test_contains_reflects_membership() -> None:
    sel: Selection = Selection()
    assert not sel.contains(7)
    sel.toggle(7)
    assert sel.contains(7)
    assert not sel.contains(8)


def test_ids_are_insertion_ordered() -> None:
    sel: Selection = Selection()
    for i in (30, 10, 20):
        sel.toggle(i)
    assert sel.ids() == (30, 10, 20)


def test_ids_preserve_order_after_remove_and_readd() -> None:
    sel: Selection = Selection()
    for i in (1, 2, 3):
        sel.toggle(i)
    sel.toggle(2)  # remove the middle
    assert sel.ids() == (1, 3)
    sel.toggle(2)  # re-add goes to the end
    assert sel.ids() == (1, 3, 2)


def test_toggle_same_id_twice_is_idempotent_in_count() -> None:
    sel: Selection = Selection()
    sel.toggle(5)
    sel.toggle(5)
    assert len(sel) == 0
    sel.toggle(5)
    assert len(sel) == 1


def test_supports_str_ids() -> None:
    sel: Selection = Selection()
    sel.toggle("abc")
    sel.toggle("def")
    assert sel.contains("abc")
    assert sel.ids() == ("abc", "def")


def test_clear_empties_selection() -> None:
    sel: Selection = Selection()
    for i in (1, 2, 3):
        sel.toggle(i)
    assert sel
    sel.clear()
    assert not sel
    assert len(sel) == 0
    assert sel.ids() == ()


def test_len_and_bool_reflect_size() -> None:
    sel: Selection = Selection()
    assert not bool(sel)
    sel.toggle(1)
    assert bool(sel)
    assert len(sel) == 1
    sel.toggle(2)
    assert len(sel) == 2


def test_module_imports_nothing_from_textual() -> None:
    module = importlib.import_module("nsc.tui.selection")
    source = inspect.getsource(module)
    assert "import textual" not in source
    assert "from textual" not in source
    referenced = {
        value.__module__
        for _, value in inspect.getmembers(module, inspect.isclass)
        if getattr(value, "__module__", "").startswith("textual")
    }
    assert not referenced
