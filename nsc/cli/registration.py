"""Walk a CommandModel and register Typer commands for read operations."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import typer
from click import Choice

from nsc.cli.handlers import handle_custom_action, handle_get, handle_list
from nsc.cli.runtime import RuntimeContext
from nsc.config.models import OutputFormat
from nsc.http.errors import NetBoxAPIError, NetBoxClientError
from nsc.model.command_model import (
    CommandModel,
    HttpMethod,
    Operation,
    Parameter,
    ParameterLocation,
    PrimitiveType,
    Resource,
)

CtxFactory = Callable[[], RuntimeContext]


def register_dynamic_commands(app: typer.Typer, model: CommandModel, get_ctx: CtxFactory) -> None:
    for tag_name, tag in sorted(model.tags.items()):
        tag_app = typer.Typer(no_args_is_help=True, help=tag.description or "")
        app.add_typer(tag_app, name=tag_name)
        for resource_name, resource in sorted(tag.resources.items()):
            resource_app = typer.Typer(no_args_is_help=True)
            tag_app.add_typer(resource_app, name=resource_name)
            _register_resource_commands(resource_app, tag_name, resource_name, resource, get_ctx)


def _register_resource_commands(
    app: typer.Typer,
    tag_name: str,
    resource_name: str,
    resource: Resource,
    get_ctx: CtxFactory,
) -> None:
    if resource.list_op is not None:
        _register_command(
            app, "list", resource.list_op, tag_name, resource_name, get_ctx, handle_list
        )
    if resource.get_op is not None:
        _register_command(app, "get", resource.get_op, tag_name, resource_name, get_ctx, handle_get)
    for action in resource.custom_actions:
        if action.http_method is not HttpMethod.GET:
            continue
        verb = _custom_action_verb(action.operation_id, resource_name)
        _register_command(app, verb, action, tag_name, resource_name, get_ctx, handle_custom_action)


def _register_command(
    app: typer.Typer,
    name: str,
    operation: Operation,
    tag_name: str,
    resource_name: str,
    get_ctx: CtxFactory,
    handler: Callable[..., None],
) -> None:
    closure = _build_closure(operation, tag_name, resource_name, get_ctx, handler)
    app.command(name=name, help=operation.summary or operation.description or "")(closure)


_GLOBAL_FLAG_NAMES: frozenset[str] = frozenset(
    {"output", "compact", "columns", "limit", "all_", "filter_"}
)


def _build_closure(
    operation: Operation,
    tag_name: str,
    resource_name: str,
    get_ctx: CtxFactory,
    handler: Callable[..., None],
) -> Callable[..., None]:
    sig_params: list[inspect.Parameter] = []
    for p in operation.parameters:
        if p.location is ParameterLocation.PATH:
            sig_params.append(_to_positional(p))
        elif p.location is ParameterLocation.QUERY:
            if "__" in p.name:
                continue
            if p.name in _GLOBAL_FLAG_NAMES:
                continue
            sig_params.append(_to_typed_option(p))

    sig_params.extend(_global_flag_params())

    def impl(**kwargs: Any) -> None:
        output = kwargs.pop("output", None)
        compact = kwargs.pop("compact", False)
        columns_csv = kwargs.pop("columns", None)
        limit = kwargs.pop("limit", None)
        fetch_all = kwargs.pop("all_", False)
        filters_raw: list[str] = kwargs.pop("filter_", None) or []
        ctx = get_ctx()
        update: dict[str, Any] = {
            "compact": compact,
            "columns_override": columns_csv.split(",") if columns_csv else None,
            "limit": limit,
            "fetch_all": fetch_all,
            "filters": [
                (item.split("=", 1)[0], item.split("=", 1)[1])
                for item in filters_raw
                if "=" in item
            ],
        }
        if output:
            update["output_format"] = OutputFormat(output)
        ctx = ctx.model_copy(update=update)
        try:
            handler(operation, op_tag=tag_name, op_resource=resource_name, ctx=ctx, **kwargs)
        except (NetBoxAPIError, NetBoxClientError) as exc:
            typer.echo(f"Error: {exc.render_for_cli()}", err=True)
            raise typer.Exit(1) from exc

    impl.__signature__ = inspect.Signature(parameters=sig_params)  # type: ignore[attr-defined]
    impl.__name__ = operation.operation_id
    return impl


def _to_positional(p: Parameter) -> inspect.Parameter:
    py_type = _python_type(p)
    return inspect.Parameter(
        name=p.name,
        kind=inspect.Parameter.KEYWORD_ONLY,
        annotation=py_type,
        default=typer.Argument(...),
    )


def _to_typed_option(p: Parameter) -> inspect.Parameter:
    flag_name = f"--{p.name.replace('_', '-')}"
    py_type: Any = _python_type(p)
    if p.enum:
        option = typer.Option(
            None,
            flag_name,
            help=p.description or "",
            click_type=Choice(p.enum, case_sensitive=True),
        )
        py_type = str | None
    elif p.primitive is PrimitiveType.BOOLEAN:
        option = typer.Option(
            None,
            f"{flag_name}/--no-{p.name.replace('_', '-')}",
            help=p.description or "",
        )
        py_type = bool | None
    elif p.primitive is PrimitiveType.ARRAY:
        option = typer.Option(None, flag_name, help=p.description or "")
        py_type = list[str] | None
    else:
        option = typer.Option(None, flag_name, help=p.description or "")
        py_type = py_type | None
    return inspect.Parameter(
        name=p.name,
        kind=inspect.Parameter.KEYWORD_ONLY,
        annotation=py_type,
        default=option,
    )


def _global_flag_params() -> list[inspect.Parameter]:
    return [
        inspect.Parameter(
            name="output",
            kind=inspect.Parameter.KEYWORD_ONLY,
            annotation=str | None,
            default=typer.Option(None, "--output", "-o"),
        ),
        inspect.Parameter(
            name="compact",
            kind=inspect.Parameter.KEYWORD_ONLY,
            annotation=bool,
            default=typer.Option(False, "--compact"),
        ),
        inspect.Parameter(
            name="columns",
            kind=inspect.Parameter.KEYWORD_ONLY,
            annotation=str | None,
            default=typer.Option(None, "--columns"),
        ),
        inspect.Parameter(
            name="limit",
            kind=inspect.Parameter.KEYWORD_ONLY,
            annotation=int | None,
            default=typer.Option(None, "--limit"),
        ),
        inspect.Parameter(
            name="all_",
            kind=inspect.Parameter.KEYWORD_ONLY,
            annotation=bool,
            default=typer.Option(False, "--all"),
        ),
        inspect.Parameter(
            name="filter_",
            kind=inspect.Parameter.KEYWORD_ONLY,
            annotation=list[str] | None,
            default=typer.Option(None, "--filter"),
        ),
    ]


def _python_type(p: Parameter) -> Any:
    match p.primitive:
        case PrimitiveType.INTEGER:
            return int
        case PrimitiveType.NUMBER:
            return float
        case PrimitiveType.BOOLEAN:
            return bool
        case _:
            return str


def _custom_action_verb(operation_id: str, resource_name: str) -> str:
    name = operation_id
    for suffix in ("_list", "_retrieve"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    if resource_name and resource_name in name:
        name = name.split(resource_name, 1)[-1].lstrip("_")
    return name.replace("_", "-") or operation_id
