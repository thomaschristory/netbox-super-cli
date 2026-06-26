"""`nsc tui [resource]` — launch the interactive Textual TUI.

Mirrors the static-command pattern in `aliases_commands.py`: the bootstrapped
`RuntimeContext` arrives as `ctx.obj[1]`. Textual is imported lazily by
`nsc.tui.run_tui`, so this module stays cheap to import.
"""

from __future__ import annotations

from typing import Annotated

import typer

from nsc.cli.runtime import RuntimeContext


def _runtime_from_ctx(ctx: typer.Context) -> RuntimeContext:
    obj = ctx.obj
    if isinstance(obj, tuple) and len(obj) == 2:  # noqa: PLR2004
        runtime = obj[1]
        if isinstance(runtime, RuntimeContext):
            return runtime
    raise typer.Exit(2)


def _save_columns(tag: str, resource: str, columns: list[str]) -> None:
    """Persist a list view's column choice to ``columns.<tag>.<resource>``."""
    from nsc.config.settings import default_paths  # noqa: PLC0415
    from nsc.config.writer import (  # noqa: PLC0415
        acquire_lock,
        atomic_write,
        dump_round_trip,
        load_round_trip,
        set_path,
    )

    path = default_paths().config_file
    with acquire_lock(path):
        doc = load_round_trip(path)
        set_path(doc, f"columns.{tag}.{resource}", list(columns))
        atomic_write(path, dump_round_trip(doc))


def register(app: typer.Typer) -> None:
    def tui(
        ctx: typer.Context,
        resource: Annotated[
            str | None,
            typer.Argument(help="Resource to open directly, e.g. 'devices'."),
        ] = None,
    ) -> None:
        """Launch the interactive TUI (navigate, filter, drill into records)."""
        runtime = _runtime_from_ctx(ctx)
        from nsc.tui import run_tui  # noqa: PLC0415  # deferred: keeps Textual lazy.

        column_prefs = {tag: dict(resources) for tag, resources in runtime.config.columns.items()}
        run_tui(
            runtime.command_model,
            runtime.client,
            initial_resource=resource,
            save_columns=_save_columns,
            column_prefs=column_prefs,
            object_colors=runtime.object_colors,
        )

    # `tui` is canonical; `interactive` and `i` are hidden aliases for the same
    # command (discoverability + a fast shortcut) without a second executable.
    app.command("tui")(tui)
    app.command("interactive", hidden=True)(tui)
    app.command("i", hidden=True)(tui)
