"""`nsc config` — read/write the user's `~/.nsc/config.yaml`.

Phase 4a ships read commands (`get`, `list`, `path`) and write commands
(`set`, `unset`, `edit`). Storage is driven by `nsc/config/writer.py` and
preserves comments + `!env` tags through round trips.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import typer
from ruamel.yaml.comments import CommentedMap

from nsc.config.settings import default_paths
from nsc.config.writer import (
    ConfigWriteError,
    acquire_lock,
    atomic_write,
    dump_round_trip,
    load_round_trip,
    set_path,
    unset_path,
)


def _config_path() -> Path:
    return default_paths().config_file


def _get_at(doc: CommentedMap, dotted: str) -> object:
    cursor: object = doc
    for key in [p for p in dotted.split(".") if p]:
        if not isinstance(cursor, CommentedMap) or key not in cursor:
            raise KeyError(dotted)
        cursor = cursor[key]
    return cursor


def _path_cmd() -> None:
    """Print the resolved config-file path."""
    typer.echo(str(_config_path()))


def _get_cmd(key: str) -> None:
    """Print the value at the given dotted path."""
    doc = load_round_trip(_config_path())
    try:
        value = _get_at(doc, key)
    except KeyError:
        typer.echo(f"error: no such key: {key}", err=True)
        raise typer.Exit(code=1) from None
    if isinstance(value, CommentedMap):
        typer.echo(dump_round_trip(value), nl=False)
    else:
        typer.echo(str(value))


def _list_cmd() -> None:
    """Print the entire config file."""
    doc = load_round_trip(_config_path())
    typer.echo(dump_round_trip(doc), nl=False)


def _set_cmd(key: str, value: str) -> None:
    """Set the value at the given dotted path. Creates parents as needed."""
    path = _config_path()
    with acquire_lock(path):
        doc = load_round_trip(path)
        try:
            set_path(doc, key, value)
        except ConfigWriteError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        atomic_write(path, dump_round_trip(doc))


def _unset_cmd(key: str) -> None:
    """Remove the leaf at the given dotted path. Prunes empty parents."""
    path = _config_path()
    with acquire_lock(path):
        doc = load_round_trip(path)
        try:
            unset_path(doc, key)
        except ConfigWriteError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        atomic_write(path, dump_round_trip(doc))


def _edit_cmd() -> None:
    """Open the config file in $EDITOR."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        atomic_write(path, "")
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        editor = shutil.which("vi") or shutil.which("nano")
    if not editor:
        typer.echo(
            "error: $EDITOR not set and no fallback editor (vi/nano) found",
            err=True,
        )
        raise typer.Exit(code=1)
    subprocess.run([editor, str(path)], check=True)


def register(app: typer.Typer) -> None:
    config_app = typer.Typer(
        name="config",
        help="Read and edit ~/.nsc/config.yaml.",
        no_args_is_help=True,
    )

    @config_app.command("path")
    def path_cmd() -> None:
        """Print the resolved config-file path."""
        _path_cmd()

    @config_app.command("get")
    def get_cmd(
        key: str = typer.Argument(..., help="Dotted path, e.g. profiles.prod.url"),
    ) -> None:
        """Print the value at the given dotted path."""
        _get_cmd(key)

    @config_app.command("list")
    def list_cmd() -> None:
        """Print the entire config file."""
        _list_cmd()

    @config_app.command("set")
    def set_cmd(
        key: str = typer.Argument(..., help="Dotted path"),
        value: str = typer.Argument(..., help="Value (string)"),
    ) -> None:
        """Set the value at the given dotted path. Creates parents as needed."""
        _set_cmd(key, value)

    @config_app.command("unset")
    def unset_cmd(
        key: str = typer.Argument(..., help="Dotted path to remove"),
    ) -> None:
        """Remove the leaf at the given dotted path. Prunes empty parents."""
        _unset_cmd(key)

    @config_app.command("edit")
    def edit_cmd() -> None:
        """Open the config file in $EDITOR."""
        _edit_cmd()

    app.add_typer(config_app)
