"""Root Typer application."""

from __future__ import annotations

import typer

from nsc._version import __version__
from nsc.cli import commands_dump

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


commands_dump.register(app)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
