from __future__ import annotations

from nsc.tui._bindings import textual_bindings
from nsc.tui.keymap import bindings_for


def test_textual_bindings_one_per_key_with_description() -> None:
    result = textual_bindings("list")
    expected_keys = sum(len(b.keys) for b in bindings_for("list"))
    assert len(result) == expected_keys
    sample = result[0]
    assert hasattr(sample, "key") and hasattr(sample, "action") and hasattr(sample, "description")
