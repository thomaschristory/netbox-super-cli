"""`nsc tui [resource]` — launch the interactive Textual TUI.

Mirrors the static-command pattern in `aliases_commands.py`: the bootstrapped
`RuntimeContext` arrives as `ctx.obj[1]`. Textual is imported lazily by
`nsc.tui.run_tui`, so this module stays cheap to import.
"""

from __future__ import annotations

from typing import Annotated

import typer

from nsc.branching.errors import BranchError
from nsc.cli.runtime import RuntimeContext, emit_envelope, map_error
from nsc.http.errors import NetBoxAPIError, NetBoxClientError


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


def _build_saved_filter_store(runtime: RuntimeContext) -> object:
    """Native NetBox SavedFilter store with a config.yaml offline fallback."""
    from nsc.config.saved_searches import ConfigFileSavedSearchStore  # noqa: PLC0415
    from nsc.savedfilters.store import NativeSavedFilterStore  # noqa: PLC0415

    fallback = ConfigFileSavedSearchStore(runtime.config)
    return NativeSavedFilterStore(runtime.client, fallback)


def _require_usable_branch(runtime: RuntimeContext) -> None:
    # Resolve up front: TUI screens only expect HTTP errors, and an unusable
    # branch must stop the session before any screen loads data.
    if runtime.branch is None:
        return
    try:
        runtime.client.ensure_branch()
    except (BranchError, NetBoxAPIError, NetBoxClientError) as exc:
        env = map_error(exc)
        raise typer.Exit(
            emit_envelope(env, output_format=runtime.output_format, color=runtime.color_stderr)
        ) from exc


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
        _require_usable_branch(runtime)
        from nsc.tui import run_tui  # noqa: PLC0415  # deferred: keeps Textual lazy.

        column_prefs = {tag: dict(resources) for tag, resources in runtime.config.columns.items()}
        run_tui(
            runtime.command_model,
            runtime.client,
            initial_resource=resource,
            save_columns=_save_columns,
            column_prefs=column_prefs,
            object_colors=runtime.object_colors,
            saved_filter_store=_build_saved_filter_store(runtime),
            branch=runtime.branch.name if runtime.branch else None,
        )

    # `tui` is canonical; `interactive` and `i` are hidden aliases for the same
    # command (discoverability + a fast shortcut) without a second executable.
    app.command("tui")(tui)
    app.command("interactive", hidden=True)(tui)
    app.command("i", hidden=True)(tui)
