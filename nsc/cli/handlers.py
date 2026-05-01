"""Three read handlers consumed by the dynamic Typer commands."""

from __future__ import annotations

import sys
from typing import Any, TextIO

import typer

from nsc.cli.runtime import RuntimeContext, apply_limit, emit_envelope, map_error
from nsc.http.errors import NetBoxAPIError, NetBoxClientError
from nsc.model.command_model import Operation, ParameterLocation
from nsc.output.render import render


def parse_filters(raw: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            raise ValueError(f"--filter expects key=value, got: {item!r}")
        key, _, value = item.partition("=")
        out[key.strip()] = value.strip()
    return out


def handle_list(
    operation: Operation,
    op_tag: str,
    op_resource: str,
    ctx: RuntimeContext,
    *,
    stream: TextIO | None = None,
    **kwargs: Any,
) -> None:
    try:
        params, _ = _split_params(operation, kwargs)
        params.update(parse_filters([f"{k}={v}" for k, v in ctx.filters]))
        iterator = ctx.client.paginate(operation.path, params)
        rows = list(
            apply_limit(
                iterator,
                limit=ctx.limit,
                fetch_all=ctx.fetch_all,
                page_size=ctx.page_size,
            )
        )
        render(
            rows,
            format=ctx.output_format,
            columns=ctx.resolve_columns(op_tag, op_resource, operation),
            stream=stream if stream is not None else sys.stdout,
            compact=ctx.compact,
        )
    except (NetBoxAPIError, NetBoxClientError) as exc:
        env = map_error(exc, operation_id=operation.operation_id)
        code = emit_envelope(env, output_format=ctx.output_format)
        raise typer.Exit(code) from exc


def handle_get(
    operation: Operation,
    op_tag: str,
    op_resource: str,
    ctx: RuntimeContext,
    *,
    stream: TextIO | None = None,
    **kwargs: Any,
) -> None:
    try:
        params, path_vars = _split_params(operation, kwargs)
        obj = ctx.client.get(operation.path.format(**path_vars), params)
        render(
            obj,
            format=ctx.output_format,
            columns=ctx.resolve_columns(op_tag, op_resource, operation),
            stream=stream if stream is not None else sys.stdout,
            compact=ctx.compact,
        )
    except (NetBoxAPIError, NetBoxClientError) as exc:
        env = map_error(exc, operation_id=operation.operation_id)
        code = emit_envelope(env, output_format=ctx.output_format)
        raise typer.Exit(code) from exc


def handle_custom_action(
    operation: Operation,
    op_tag: str,
    op_resource: str,
    ctx: RuntimeContext,
    *,
    stream: TextIO | None = None,
    **kwargs: Any,
) -> None:
    handle_get(operation, op_tag, op_resource, ctx, stream=stream, **kwargs)


def _split_params(
    operation: Operation, kwargs: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    path_names = {p.name for p in operation.parameters if p.location is ParameterLocation.PATH}
    query: dict[str, Any] = {}
    path: dict[str, Any] = {}
    for k, v in kwargs.items():
        if v is None:
            continue
        if k in path_names:
            path[k] = v
        else:
            query[k] = v
    return query, path
