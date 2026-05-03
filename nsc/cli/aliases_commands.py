"""`nsc ls / get / rm / search` — curated aliases over the dynamic command tree.

Each verb resolves its term to a `(tag, resource, operation)` triple via
`nsc.aliases.resolve` and delegates to the same handler the dynamic tree
uses. The audit log is written by the handler (or by `NetBoxClient` for
write methods), so alias and full-path invocations produce byte-identical
`audit.jsonl` lines (modulo timestamp and duration_ms).
"""

from __future__ import annotations

from typing import Annotated

import typer

from nsc.aliases import (
    AliasVerb,
    AmbiguousAlias,
    ResolvedAlias,
    UnknownAlias,
    resolve,
)
from nsc.cli.handlers import handle_list
from nsc.cli.runtime import RuntimeContext, emit_envelope
from nsc.config.models import OutputFormat
from nsc.output.errors import (
    ErrorEnvelope,
    ambiguous_alias_envelope,
    unknown_alias_envelope,
)


def _runtime_from_ctx(ctx: typer.Context) -> RuntimeContext:
    """Extract the bootstrapped RuntimeContext from `ctx.obj`."""
    obj = ctx.obj
    if isinstance(obj, tuple) and len(obj) == 2:  # noqa: PLR2004
        runtime = obj[1]
        if isinstance(runtime, RuntimeContext):
            return runtime
    raise typer.Exit(2)


def _emit_alias_envelope(env: ErrorEnvelope, ctx: RuntimeContext) -> int:
    return emit_envelope(env, output_format=ctx.output_format)


def register(app: typer.Typer) -> None:
    @app.command("ls", help="List records on a resource (alias for `<tag> <resource> list`).")
    def ls_cmd(
        ctx: typer.Context,
        term: Annotated[str, typer.Argument(help="Resource name (plural, e.g. `devices`).")],
        output: Annotated[str | None, typer.Option("--output", "-o")] = None,
        compact: Annotated[bool, typer.Option("--compact")] = False,
        columns: Annotated[str | None, typer.Option("--columns")] = None,
        limit: Annotated[int | None, typer.Option("--limit")] = None,
        all_: Annotated[bool, typer.Option("--all")] = False,
        filter_: Annotated[list[str] | None, typer.Option("--filter")] = None,
    ) -> None:
        runtime = _runtime_from_ctx(ctx)
        update: dict[str, object] = {
            "compact": compact,
            "columns_override": columns.split(",") if columns else None,
            "limit": limit,
            "fetch_all": all_,
            "filters": [
                (item.split("=", 1)[0], item.split("=", 1)[1])
                for item in (filter_ or [])
                if "=" in item
            ],
        }
        if output:
            update["output_format"] = OutputFormat(output)
        runtime = runtime.model_copy(update=update)

        result = resolve(AliasVerb.LS, term, runtime.command_model)
        if isinstance(result, AmbiguousAlias):
            env = ambiguous_alias_envelope(verb="ls", term=term, candidates=result.candidates)
            raise typer.Exit(_emit_alias_envelope(env, runtime))
        if isinstance(result, UnknownAlias):
            env = unknown_alias_envelope(verb="ls", term=term, reason=result.reason)
            raise typer.Exit(_emit_alias_envelope(env, runtime))
        assert isinstance(result, ResolvedAlias)
        handle_list(
            result.operation,
            op_tag=result.tag,
            op_resource=result.resource_name,
            ctx=runtime,
        )
