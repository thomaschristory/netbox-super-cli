"""`nsc commands` — dump the generated CommandModel as JSON.

In Phase 1 this is the only useful subcommand. It exists so an agent or human
can see exactly what the schema-derived command tree would look like, without
needing the dynamic Typer registration that Phase 2 will add.
"""

from __future__ import annotations

import json
import sys
from enum import StrEnum

import typer

from nsc.builder.build import build_command_model
from nsc.schema.loader import SchemaLoadError, load_schema


class _Output(StrEnum):
    JSON = "json"


def register(app: typer.Typer) -> None:
    @app.command("commands")
    def commands_dump(
        schema: str = typer.Option(
            ...,
            "--schema",
            help="Path or URL to an OpenAPI schema. Required in Phase 1.",
        ),
        output: _Output = typer.Option(  # noqa: B008
            _Output.JSON,
            "--output",
            "-o",
            help="Output format. Phase 1 supports `json` only.",
        ),
        compact: bool = typer.Option(
            False,
            "--compact",
            help="Emit a single-line JSON object instead of indented output.",
        ),
    ) -> None:
        """Dump the schema-derived command tree."""
        try:
            loaded = load_schema(schema)
        except SchemaLoadError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=2) from exc

        model = build_command_model(loaded)

        if output is _Output.JSON:
            indent = None if compact else 2
            payload = json.loads(model.model_dump_json())
            json.dump(payload, sys.stdout, indent=indent, sort_keys=False)
            sys.stdout.write("\n")
