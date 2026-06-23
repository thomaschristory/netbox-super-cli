"""Interactive Textual TUI for nsc. Textual is imported lazily by `run_tui`."""

from __future__ import annotations

__all__ = ["run_tui"]


def run_tui(*args: object, **kwargs: object) -> None:
    """Lazy entrypoint so importing `nsc.tui` never imports Textual eagerly."""
    from nsc.tui.app import run_tui as _run  # noqa: PLC0415  # deferred: keeps Textual lazy.

    _run(*args, **kwargs)
