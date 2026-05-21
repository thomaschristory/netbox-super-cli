"""`nsc commands` — dump the generated CommandModel as JSON."""

from __future__ import annotations

import json
import os
import sys
from enum import StrEnum

import typer

from nsc.builder.build import build_command_model
from nsc.cli.globals import GlobalState
from nsc.cli.runtime import resolve_transport_settings
from nsc.schema.loader import SchemaLoadError, load_schema


class _Output(StrEnum):
    JSON = "json"


def register(app: typer.Typer) -> None:
    @app.command("commands")
    def commands_dump(
        ctx: typer.Context,
        schema: str = typer.Option(
            ...,
            "--schema",
            help="Path or URL to an OpenAPI schema.",
        ),
        output: _Output = typer.Option(  # noqa: B008
            _Output.JSON,
            "--output",
            "-o",
            help="Output format.",
        ),
        compact: bool = typer.Option(
            False,
            "--compact",
            help="Emit a single-line JSON object instead of indented output.",
        ),
    ) -> None:
        """Dump the schema-derived command tree."""
        verify_ssl = True
        timeout = 30.0
        state = ctx.obj
        if isinstance(state, GlobalState):
            verify_ssl, timeout = resolve_transport_settings(
                state.config, state.overrides, env=os.environ
            )

        try:
            loaded = load_schema(schema, verify_ssl=verify_ssl, timeout=timeout)
        except SchemaLoadError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=2) from exc

        model = build_command_model(loaded)

        if output is _Output.JSON:
            indent = None if compact else 2
            payload = json.loads(model.model_dump_json())
            json.dump(payload, sys.stdout, indent=indent, sort_keys=False)
            sys.stdout.write("\n")
