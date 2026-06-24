"""Interactive Textual TUI for nsc. Textual is imported lazily by `run_tui`."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nsc.model.command_model import CommandModel

__all__ = ["run_tui"]


def run_tui(
    model: CommandModel,
    client: Any,
    *,
    initial_resource: str | None = None,
    save_columns: Callable[[str, str, list[str]], None] | None = None,
    column_prefs: dict[str, dict[str, list[str]]] | None = None,
) -> None:
    """Lazy entrypoint so importing `nsc.tui` never imports Textual eagerly."""
    from nsc.tui.app import run_tui as _run  # noqa: PLC0415  # deferred: keeps Textual lazy.

    _run(
        model,
        client,
        initial_resource=initial_resource,
        save_columns=save_columns,
        column_prefs=column_prefs,
    )
