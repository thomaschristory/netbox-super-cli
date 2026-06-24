"""Bridge the pure keymap to Textual ``Binding`` objects (the only coupling point)."""

from __future__ import annotations

from textual.binding import Binding, BindingType

from nsc.tui.keymap import bindings_for


def textual_bindings(context: str) -> list[BindingType]:
    bindings: list[BindingType] = []
    for b in bindings_for(context):
        for key in b.keys:
            bindings.append(
                Binding(key=key, action=b.action, description=b.description, show=b.show)
            )
    return bindings
