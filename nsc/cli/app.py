"""Root Typer application.

Phase 1 only registers the meta-command `commands`. Resource-tree registration
happens in Phase 2.
"""

from __future__ import annotations

import typer

from nsc._version import __version__

app = typer.Typer(
    name="nsc",
    help="netbox-super-cli — dynamic NetBox CLI driven by the live OpenAPI schema.",
    no_args_is_help=True,
    add_completion=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"nsc {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the nsc version and exit.",
    ),
) -> None:
    """Root callback — global options live here."""


def main() -> None:
    """Entry point used by `pyproject.toml` console scripts."""
    app()


if __name__ == "__main__":
    main()
