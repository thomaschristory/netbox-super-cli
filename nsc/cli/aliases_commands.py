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
from nsc.cli.handlers import handle_delete, handle_get, handle_list
from nsc.cli.runtime import RuntimeContext, emit_envelope
from nsc.config.models import OutputFormat
from nsc.http.errors import NetBoxAPIError, NetBoxClientError
from nsc.model.command_model import Operation
from nsc.output.errors import (
    ErrorEnvelope,
    ErrorType,
    ambiguous_alias_envelope,
    client_envelope,
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


def _dereference_by_name(
    runtime: RuntimeContext,
    *,
    list_op: Operation,
    name: str,
) -> int | ErrorEnvelope:
    """List the resource filtered by `name=<name>` and return the single id.

    Returns an `ErrorEnvelope` (already-shaped ambiguous_alias / unknown_alias)
    if zero or >=2 records match. Caller emits and exits.
    """
    try:
        rows = list(runtime.client.paginate(list_op.path, {"name": name}))
    except (NetBoxAPIError, NetBoxClientError) as exc:
        return client_envelope(
            f"failed to dereference name {name!r}: {exc}",
            operation_id=list_op.operation_id,
        )
    if len(rows) == 0:
        return ErrorEnvelope(
            error=f"no record matched name={name!r}",
            type=ErrorType.UNKNOWN_ALIAS,
            details={"verb": "rm", "term": name, "reason": "name_not_found"},
        )
    if len(rows) >= 2:  # noqa: PLR2004
        return ErrorEnvelope(
            error=f"{len(rows)} records matched name={name!r}; refuse to delete",
            type=ErrorType.AMBIGUOUS_ALIAS,
            details={
                "verb": "rm",
                "term": name,
                "reason": "name_matched_multiple",
                "matched_ids": [row["id"] for row in rows],
            },
        )
    return int(rows[0]["id"])


def register(app: typer.Typer) -> None:  # noqa: PLR0915
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

    @app.command("rm", help="Delete one record (alias for `<tag> <resource> delete`).")
    def rm_cmd(
        ctx: typer.Context,
        term: Annotated[str, typer.Argument(help="Resource name (plural).")],
        id_or_name: Annotated[str, typer.Argument(help="Numeric id or unique name.")],
        apply: Annotated[bool, typer.Option("--apply", "-a")] = False,
        explain: Annotated[bool, typer.Option("--explain")] = False,
        strict: Annotated[bool, typer.Option("--strict")] = False,
        output: Annotated[str | None, typer.Option("--output", "-o")] = None,
    ) -> None:
        runtime = _runtime_from_ctx(ctx)
        update: dict[str, object] = {
            "apply": apply,
            "explain": explain,
            "strict": strict,
        }
        if output:
            update["output_format"] = OutputFormat(output)
        runtime = runtime.model_copy(update=update)

        result = resolve(AliasVerb.RM, term, runtime.command_model)
        if isinstance(result, AmbiguousAlias):
            env = ambiguous_alias_envelope(verb="rm", term=term, candidates=result.candidates)
            raise typer.Exit(_emit_alias_envelope(env, runtime))
        if isinstance(result, UnknownAlias):
            env = unknown_alias_envelope(verb="rm", term=term, reason=result.reason)
            raise typer.Exit(_emit_alias_envelope(env, runtime))
        assert isinstance(result, ResolvedAlias)

        if id_or_name.isdigit():
            resolved_id = int(id_or_name)
        else:
            resource = runtime.command_model.tags[result.tag].resources[result.resource_name]
            list_op = resource.list_op
            if list_op is None:
                env = unknown_alias_envelope(
                    verb="rm", term=term, reason="no_list_op_for_dereference"
                )
                raise typer.Exit(_emit_alias_envelope(env, runtime))
            outcome = _dereference_by_name(runtime, list_op=list_op, name=id_or_name)
            if isinstance(outcome, ErrorEnvelope):
                raise typer.Exit(_emit_alias_envelope(outcome, runtime))
            resolved_id = outcome

        handle_delete(
            result.operation,
            op_tag=result.tag,
            op_resource=result.resource_name,
            ctx=runtime,
            id=str(resolved_id),
        )

    @app.command("get", help="Get one record (alias for `<tag> <resource> get`).")
    def get_cmd(
        ctx: typer.Context,
        term: Annotated[str, typer.Argument(help="Resource name (plural).")],
        id_or_name: Annotated[str, typer.Argument(help="Numeric id or unique name.")],
        output: Annotated[str | None, typer.Option("--output", "-o")] = None,
        compact: Annotated[bool, typer.Option("--compact")] = False,
        columns: Annotated[str | None, typer.Option("--columns")] = None,
    ) -> None:
        runtime = _runtime_from_ctx(ctx)
        update: dict[str, object] = {
            "compact": compact,
            "columns_override": columns.split(",") if columns else None,
        }
        if output:
            update["output_format"] = OutputFormat(output)
        runtime = runtime.model_copy(update=update)

        result = resolve(AliasVerb.GET, term, runtime.command_model)
        if isinstance(result, AmbiguousAlias):
            env = ambiguous_alias_envelope(verb="get", term=term, candidates=result.candidates)
            raise typer.Exit(_emit_alias_envelope(env, runtime))
        if isinstance(result, UnknownAlias):
            env = unknown_alias_envelope(verb="get", term=term, reason=result.reason)
            raise typer.Exit(_emit_alias_envelope(env, runtime))
        assert isinstance(result, ResolvedAlias)

        if id_or_name.isdigit():
            resolved_id = int(id_or_name)
        else:
            list_op = runtime.command_model.tags[result.tag].resources[result.resource_name].list_op
            if list_op is None:
                env = unknown_alias_envelope(
                    verb="get", term=term, reason="no_list_op_for_dereference"
                )
                raise typer.Exit(_emit_alias_envelope(env, runtime))
            outcome = _dereference_by_name(runtime, list_op=list_op, name=id_or_name)
            if isinstance(outcome, ErrorEnvelope):
                outcome = outcome.model_copy(update={"details": {**outcome.details, "verb": "get"}})
                raise typer.Exit(_emit_alias_envelope(outcome, runtime))
            resolved_id = outcome

        handle_get(
            result.operation,
            op_tag=result.tag,
            op_resource=result.resource_name,
            ctx=runtime,
            id=str(resolved_id),
        )
