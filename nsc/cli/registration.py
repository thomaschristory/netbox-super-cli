"""Walk a CommandModel and register Typer commands for read AND write operations."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import typer
from click import Choice

from nsc.cli.handlers import (
    handle_create,
    handle_custom_action,
    handle_custom_action_write,
    handle_delete,
    handle_get,
    handle_list,
    handle_update,
)
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
        _register_read(app, "list", resource.list_op, tag_name, resource_name, get_ctx, handle_list)
    if resource.get_op is not None:
        _register_read(app, "get", resource.get_op, tag_name, resource_name, get_ctx, handle_get)
    if resource.create_op is not None:
        _register_write(
            app, "create", resource.create_op, tag_name, resource_name, get_ctx, handle_create
        )
    if resource.update_op is not None:
        _register_write(
            app, "update", resource.update_op, tag_name, resource_name, get_ctx, handle_update
        )
    if resource.replace_op is not None:
        _register_write(
            app, "replace", resource.replace_op, tag_name, resource_name, get_ctx, handle_update
        )
    if resource.delete_op is not None:
        _register_write(
            app, "delete", resource.delete_op, tag_name, resource_name, get_ctx, handle_delete
        )
    for action in resource.custom_actions:
        if action.http_method is HttpMethod.GET:
            verb = _custom_action_verb(action.operation_id, resource_name, is_write=False)
            _register_read(
                app, verb, action, tag_name, resource_name, get_ctx, handle_custom_action
            )
        elif action.http_method in {
            HttpMethod.POST,
            HttpMethod.PATCH,
            HttpMethod.PUT,
            HttpMethod.DELETE,
        }:
            verb = _custom_action_verb(action.operation_id, resource_name, is_write=True)
            _register_write(
                app, verb, action, tag_name, resource_name, get_ctx, handle_custom_action_write
            )


def _register_read(
    app: typer.Typer,
    name: str,
    operation: Operation,
    tag_name: str,
    resource_name: str,
    get_ctx: CtxFactory,
    handler: Callable[..., None],
) -> None:
    closure = _build_read_closure(operation, tag_name, resource_name, get_ctx, handler)
    app.command(name=name, help=operation.summary or operation.description or "")(closure)


def _register_write(
    app: typer.Typer,
    name: str,
    operation: Operation,
    tag_name: str,
    resource_name: str,
    get_ctx: CtxFactory,
    handler: Callable[..., None],
) -> None:
    closure = _build_write_closure(operation, tag_name, resource_name, get_ctx, handler)
    app.command(name=name, help=operation.summary or operation.description or "")(closure)


_GLOBAL_FLAG_NAMES: frozenset[str] = frozenset(
    {"output", "compact", "columns", "limit", "all_", "filter_"}
)


def _build_read_closure(
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


def _build_write_closure(
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
        # Query parameters on writes are rare in NetBox; skip them in 3b.

    sig_params.extend(_write_flag_params())

    def impl(**kwargs: Any) -> None:
        output = kwargs.pop("output", None)
        compact = kwargs.pop("compact", False)
        columns_csv = kwargs.pop("columns", None)
        apply_flag: bool = kwargs.pop("apply", False)
        explain: bool = kwargs.pop("explain", False)
        strict: bool = kwargs.pop("strict", False)
        file: str | None = kwargs.pop("file", None)
        fields_raw: list[str] = list(kwargs.pop("field", None) or [])
        format_: str | None = kwargs.pop("format_", None)
        ctx = get_ctx()
        update: dict[str, Any] = {
            "compact": compact,
            "columns_override": columns_csv.split(",") if columns_csv else None,
            "apply": apply_flag,
            "explain": explain,
            "strict": strict,
            "file": file,
            "fields": fields_raw,
            "file_format": format_,
        }
        if output:
            update["output_format"] = OutputFormat(output)
        ctx = ctx.model_copy(update=update)
        handler(operation, op_tag=tag_name, op_resource=resource_name, ctx=ctx, **kwargs)

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


def _write_flag_params() -> list[inspect.Parameter]:
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
            name="apply",
            kind=inspect.Parameter.KEYWORD_ONLY,
            annotation=bool,
            default=typer.Option(
                False,
                "--apply",
                "-a",
                help="Send the request. Without this, dry-run only (no wire effect).",
            ),
        ),
        inspect.Parameter(
            name="explain",
            kind=inspect.Parameter.KEYWORD_ONLY,
            annotation=bool,
            default=typer.Option(
                False,
                "--explain",
                help="Print the resolved request and field-level provenance.",
            ),
        ),
        inspect.Parameter(
            name="strict",
            kind=inspect.Parameter.KEYWORD_ONLY,
            annotation=bool,
            default=typer.Option(
                False,
                "--strict",
                help="On DELETE: fail with exit 9 if the object is already absent.",
            ),
        ),
        inspect.Parameter(
            name="file",
            kind=inspect.Parameter.KEYWORD_ONLY,
            annotation=str | None,
            default=typer.Option(
                None,
                "-f",
                "--file",
                help="Path to a yaml/yml/json file with the request body. Use `-` for stdin.",
            ),
        ),
        inspect.Parameter(
            name="field",
            kind=inspect.Parameter.KEYWORD_ONLY,
            annotation=list[str] | None,
            default=typer.Option(
                None,
                "--field",
                help=(
                    "key=value field override; repeatable; dotted paths allowed "
                    "(site.name=us-east-1)."
                ),
            ),
        ),
        inspect.Parameter(
            name="format_",
            kind=inspect.Parameter.KEYWORD_ONLY,
            annotation=str | None,
            default=typer.Option(
                None,
                "--format",
                help="Override file-format detection (yaml|yml|json).",
            ),
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


def _custom_action_verb(operation_id: str, resource_name: str, *, is_write: bool) -> str:
    """Derive a CLI verb from a custom-action operationId.

    Reads strip `_list`/`_retrieve` so list/retrieve custom-actions read
    naturally (e.g. `available-asns list` → `available-asns`). Writes keep
    their action suffix so PUT/PATCH/DELETE on the same base don't collide
    in the command tree.
    """
    name = operation_id
    read_suffixes = ("_list", "_retrieve")
    if not is_write:
        for suffix in read_suffixes:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
    res_underscored = resource_name.replace("-", "_") if resource_name else ""
    if res_underscored and res_underscored in name:
        name = name.split(res_underscored, 1)[-1].lstrip("_")
    return name.replace("_", "-") or operation_id
