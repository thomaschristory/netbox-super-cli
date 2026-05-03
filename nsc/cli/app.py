"""Root Typer application."""

from __future__ import annotations

from typing import Annotated, Any

import click
import typer
from typer.core import TyperGroup
from typer.main import get_group_from_info

from nsc._version import __version__
from nsc.cli import (
    aliases_commands,
    commands_dump,
    config_commands,
    init_commands,
    login_commands,
    profiles_commands,
)
from nsc.cli.globals import GlobalState, build_runtime_context
from nsc.cli.registration import register_dynamic_commands
from nsc.cli.runtime import (
    CLIOverrides,
    NoProfileError,
    RuntimeContext,
    UnknownProfileError,
    emit_envelope,
    map_error,
)
from nsc.config import default_paths
from nsc.config.loader import ConfigParseError, load_config
from nsc.config.models import Config, OutputFormat
from nsc.http.errors import NetBoxAPIError, NetBoxClientError
from nsc.schema.source import SchemaSourceError

# Mutable dict used as a single-slot holder to avoid `global` statements.
# Keys: "runtime" -> RuntimeContext | None, "error" -> Exception | None.
_invocation: dict[str, object] = {"runtime": None, "error": None}

# Static subcommands that do not need a profile.
_META_COMMANDS: frozenset[str] = frozenset({"commands", "config", "init", "login", "profiles"})


def _extract_global_overrides(args: list[str]) -> CLIOverrides:
    """Scan raw argv for global flags without consuming the full Click context."""
    kwargs: dict[str, object] = {}
    two_arg = {
        "--profile": "profile",
        "--url": "url",
        "--token": "token",
        "--schema": "schema_override",
        "--output": "output",
        "-o": "output",
    }
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--") and "=" in a:
            flag, _, value = a.partition("=")
            if flag in two_arg:
                kwargs[two_arg[flag]] = value
            i += 1
            continue
        if a in two_arg and i + 1 < len(args):
            kwargs[two_arg[a]] = args[i + 1]
            i += 2
            continue
        if a == "--insecure":
            kwargs["insecure"] = True
            i += 1
            continue
        if a == "--no-insecure":
            kwargs["insecure"] = False
            i += 1
            continue
        i += 1
    return CLIOverrides(**kwargs)  # type: ignore[arg-type]


def _first_non_option(args: list[str]) -> str | None:
    """Return the first arg that looks like a subcommand name (not a flag/value)."""
    skip_next = False
    skip_flags = {
        "--profile",
        "--url",
        "--token",
        "--schema",
        "--output",
        "-o",
    }
    for a in args:
        if skip_next:
            skip_next = False
            continue
        if a in skip_flags:
            skip_next = True
            continue
        if a.startswith("-"):
            continue
        return a
    return None


class _BootstrappingGroup(TyperGroup):
    """TyperGroup subclass that registers dynamic commands before dispatch.

    Overrides `make_context` (called once per invocation, before `resolve_command`)
    so dynamic Typer commands are visible to Click's command resolver.
    """

    def make_context(
        self,
        info_name: str | None,
        args: list[str],
        parent: click.Context | None = None,
        **extra: Any,
    ) -> click.Context:
        _invocation["runtime"] = None
        _invocation["error"] = None

        subcommand = _first_non_option(args)

        if subcommand not in _META_COMMANDS:
            overrides = _extract_global_overrides(args)
            debug = "--debug" in args
            try:
                config = load_config(default_paths().config_file)
            except ConfigParseError as exc:
                _invocation["error"] = exc
                return super().make_context(info_name, args, parent, **extra)

            state = GlobalState(overrides=overrides, config=config, debug=debug)

            try:
                runtime = build_runtime_context(state)
            except (NoProfileError, UnknownProfileError, SchemaSourceError) as exc:
                _invocation["error"] = exc
                return super().make_context(info_name, args, parent, **extra)

            _invocation["runtime"] = runtime
            # `app` is defined after this class; by call time it is available.
            register_dynamic_commands(app, runtime.command_model, lambda: runtime)
            # Sync newly added Typer sub-apps into this Click group's commands
            # dict. Typer builds its Click group once at invocation time from
            # `app.registered_groups`; commands added inside `make_context`
            # would otherwise be invisible to `resolve_command`.
            for group_info in app.registered_groups:
                sub = get_group_from_info(
                    group_info,
                    pretty_exceptions_short=app.pretty_exceptions_short,
                    rich_markup_mode=app.rich_markup_mode,
                    suggest_commands=app.suggest_commands,
                )
                if sub.name and sub.name not in self.commands:
                    self.commands[sub.name] = sub

        return super().make_context(info_name, args, parent, **extra)

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        # Surface a bootstrap error when the requested command was not registered
        # (because bootstrap failed). SchemaSourceError exits 3 per spec; all
        # other bootstrap errors are usage errors (exit 2).
        error = _invocation["error"]
        if error is not None and args and args[0] not in self.commands:
            if isinstance(error, SchemaSourceError):
                # Exit code 3 matches EXIT_CODES[ErrorType.SCHEMA] — keep in sync.
                typer.echo(f"Error: {error}", err=True)
                raise typer.Exit(3)
            ctx.fail(str(error))
        return super().resolve_command(ctx, args)


app = typer.Typer(
    name="nsc",
    help="netbox-super-cli — dynamic NetBox CLI driven by the live OpenAPI schema.",
    no_args_is_help=True,
    add_completion=True,
    cls=_BootstrappingGroup,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"nsc {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the nsc version and exit.",
        ),
    ] = False,
    profile: Annotated[str | None, typer.Option("--profile")] = None,
    url: Annotated[str | None, typer.Option("--url")] = None,
    token: Annotated[str | None, typer.Option("--token")] = None,
    insecure: Annotated[bool | None, typer.Option("--insecure/--no-insecure")] = None,
    schema: Annotated[str | None, typer.Option("--schema")] = None,
    output: Annotated[str | None, typer.Option("--output", "-o")] = None,
    debug: Annotated[bool, typer.Option("--debug")] = False,
) -> None:
    """Root callback — global options live here."""
    overrides = CLIOverrides(
        profile=profile,
        url=url,
        token=token,
        insecure=insecure,
        schema_override=schema,
        output=output,
    )
    try:
        config = load_config(default_paths().config_file)
    except ConfigParseError as exc:
        if ctx.invoked_subcommand in ("init", "login", "profiles"):
            config = Config()
        else:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(2) from exc

    state = GlobalState(overrides=overrides, config=config, debug=debug)
    ctx.obj = state

    if ctx.invoked_subcommand in _META_COMMANDS or ctx.invoked_subcommand is None:
        return

    runtime = _invocation["runtime"]
    if isinstance(runtime, RuntimeContext):
        ctx.obj = (state, runtime)


commands_dump.register(app)
config_commands.register(app)
init_commands.register(app)
login_commands.register(app)
profiles_commands.register(app)
aliases_commands.register(app)


def main() -> None:
    try:
        app()
    except typer.Exit:
        raise
    except (NetBoxAPIError, NetBoxClientError) as exc:
        env = map_error(exc)
        code = emit_envelope(env, output_format=OutputFormat.TABLE)
        raise typer.Exit(code) from exc
    except Exception as exc:  # catch-all to produce internal envelope
        env = map_error(exc)
        code = emit_envelope(env, output_format=OutputFormat.TABLE)
        raise typer.Exit(code) from exc


if __name__ == "__main__":
    main()
