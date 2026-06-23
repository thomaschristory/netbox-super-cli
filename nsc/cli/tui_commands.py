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


def register(app: typer.Typer) -> None:
    @app.command("tui")
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

        run_tui(runtime.command_model, runtime.client, initial_resource=resource)
