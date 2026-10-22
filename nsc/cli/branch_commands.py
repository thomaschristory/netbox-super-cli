"""`nsc branch …` — NetBox Branching lifecycle commands.

Every subcommand talks to NetBox through an *unbranched* client: the branch
endpoints live outside branch context, and `nsc branch use --main` must keep
working when the sticky branch has been merged or deleted.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Annotated, Any, NoReturn

import typer

from nsc.branching.api import (
    create_branch,
    list_branches,
    list_changes,
    wait_until_ready,
)
from nsc.branching.errors import BranchError
from nsc.branching.models import Branch, choice_value
from nsc.branching.resolve import get_branch, require_ready
from nsc.cache.store import ADHOC_PROFILE
from nsc.cli.runtime import RuntimeContext, emit_envelope, map_error
from nsc.config.models import OutputFormat
from nsc.http.client import NetBoxClient
from nsc.http.errors import NetBoxAPIError, NetBoxClientError
from nsc.output.errors import ErrorEnvelope, ErrorType
from nsc.output.render import render

_DEFAULT_TIMEOUT = 600.0

_Output = Annotated[str | None, typer.Option("--output", "-o")]
_Timeout = Annotated[
    float, typer.Option("--timeout", help="Seconds to wait for the server-side job.")
]
_NoWait = Annotated[bool, typer.Option("--no-wait", help="Return as soon as the job is queued.")]
_Apply = Annotated[bool, typer.Option("--apply", help="Actually do it (default: dry-run).")]
_AckConflicts = Annotated[
    bool,
    typer.Option(
        "--acknowledge-conflicts",
        help="Proceed despite conflicts with main; branch values win.",
    ),
]
_OptionalName = Annotated[
    str | None, typer.Argument(help="Branch name or schema_id (default: the active branch).")
]

_BRANCH_COLUMNS = ["name", "status", "schema_id", "owner", "last_sync", "active"]
_DIFF_COLUMNS = ["action", "object_type", "object", "fields"]
_JOB_COLUMNS = ["id", "status", "completed", "error"]


def _runtime_from_ctx(ctx: typer.Context) -> RuntimeContext:
    obj = ctx.obj
    if isinstance(obj, tuple) and len(obj) == 2:  # noqa: PLR2004
        runtime = obj[1]
        if isinstance(runtime, RuntimeContext):
            return runtime
    raise typer.Exit(2)


def _unbranched_client(runtime: RuntimeContext) -> NetBoxClient:
    return NetBoxClient(
        runtime.resolved_profile,  # type: ignore[arg-type]
        debug=runtime.debug,
        redaction=runtime.config.defaults.audit_redaction,
        profile_name=runtime.resolved_profile.name,
    )


def _fail(runtime: RuntimeContext, env: ErrorEnvelope) -> NoReturn:
    raise typer.Exit(
        emit_envelope(env, output_format=runtime.output_format, color=runtime.color_stderr)
    )


@contextmanager
def _session(runtime: RuntimeContext) -> Iterator[NetBoxClient]:
    try:
        with _unbranched_client(runtime) as client:
            yield client
    except (BranchError, NetBoxAPIError, NetBoxClientError) as exc:
        _fail(runtime, map_error(exc))


def _target_ref(runtime: RuntimeContext, name: str | None) -> str:
    if name:
        return name
    if runtime.branch is not None:
        return runtime.branch.name
    _fail(
        runtime,
        ErrorEnvelope(
            error="no branch given and none active; pass a branch name or select one "
            "with `nsc branch use NAME`",
            type=ErrorType.INPUT_ERROR,
        ),
    )


def _emit(runtime: RuntimeContext, data: Any, columns: list[str] | None = None) -> None:
    render(
        data,
        format=runtime.output_format,
        columns=columns,
        stream=sys.stdout,
        compact=runtime.compact,
        color=runtime.color,
    )


def _branch_row(branch: Branch, active: str | None) -> dict[str, Any]:
    row = branch.model_dump()
    row["active"] = active is not None and active in (branch.name, branch.schema_id)
    return row


def _changed_fields(change: dict[str, Any]) -> list[str]:
    before = change.get("original") or {}
    after = change.get("modified") or {}
    keys = sorted(set(before) | set(after))
    return [k for k in keys if before.get(k) != after.get(k)]


def _diff_row(change: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": choice_value(change.get("action")),
        "object_type": change.get("object_type"),
        "object": change.get("object_repr") or change.get("object_id"),
        "fields": ", ".join(_changed_fields(change)),
    }


def _write_profile_branch(runtime: RuntimeContext, value: str | None) -> None:
    from nsc.config.settings import default_paths  # noqa: PLC0415
    from nsc.config.writer import (  # noqa: PLC0415
        acquire_lock,
        atomic_write,
        dump_round_trip,
        load_round_trip,
        set_path,
        unset_path,
    )

    path = default_paths().config_file
    key = f"profiles.{runtime.resolved_profile.name}.branch"
    with acquire_lock(path):
        doc = load_round_trip(path)
        if value is None:
            unset_path(doc, key)
        else:
            set_path(doc, key, value)
        atomic_write(path, dump_round_trip(doc))


def _require_saved_profile(runtime: RuntimeContext, name: str | None) -> None:
    if runtime.resolved_profile.name != ADHOC_PROFILE:
        return
    hint = name or "<name>"
    _fail(
        runtime,
        ErrorEnvelope(
            error="no saved profile to store the branch on; "
            f"set NSC_BRANCH={hint} or pass --branch {hint}",
            type=ErrorType.CONFIG,
        ),
    )


def _use(runtime: RuntimeContext, branch: Branch) -> None:
    _write_profile_branch(runtime, branch.name)
    print(
        f"now using branch {branch.name} on profile {runtime.resolved_profile.name}",
        file=sys.stderr,
    )


def list_cmd(ctx: typer.Context, output: _Output = None) -> None:
    """List branches; the active one is marked."""
    runtime = _runtime_from_ctx(ctx)
    active = runtime.branch.name if runtime.branch else None
    with _session(runtime) as client:
        rows = [_branch_row(b, active) for b in list_branches(client)]
    _emit(runtime, rows, _BRANCH_COLUMNS)


def show_cmd(ctx: typer.Context, name: _OptionalName = None, output: _Output = None) -> None:
    """Show one branch (default: the active branch)."""
    runtime = _runtime_from_ctx(ctx)
    ref = _target_ref(runtime, name)
    with _session(runtime) as client:
        branch = get_branch(client, ref)
    _emit(runtime, branch.model_dump())


def current_cmd(ctx: typer.Context, output: _Output = None) -> None:
    """Print the active branch and where it was selected, or `main`."""
    runtime = _runtime_from_ctx(ctx)
    selection = runtime.branch
    if runtime.output_format is OutputFormat.TABLE:
        typer.echo(f"{selection.name} ({selection.source})" if selection else "main")
        return
    _emit(
        runtime,
        {
            "branch": selection.name if selection else None,
            "source": selection.source if selection else None,
        },
    )


def create_cmd(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Name of the new branch.")],
    description: Annotated[str, typer.Option("--description")] = "",
    use: Annotated[
        bool, typer.Option("--use", help="Make it the profile's active branch once ready.")
    ] = False,
    no_wait: _NoWait = False,
    timeout: _Timeout = _DEFAULT_TIMEOUT,
    output: _Output = None,
) -> None:
    """Create a branch and wait until it is ready."""
    runtime = _runtime_from_ctx(ctx)
    if use:
        _require_saved_profile(runtime, name)
    with _session(runtime) as client:
        branch = create_branch(client, name, description)
        if not no_wait or use:
            branch = wait_until_ready(client, branch, timeout=timeout, sleep=time.sleep)
    if use:
        _use(runtime, branch)
    _emit(runtime, branch.model_dump())


def use_cmd(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Argument(help="Branch name or schema_id.")] = None,
    main: Annotated[
        bool, typer.Option("--main", help="Clear the active branch; work on main.")
    ] = False,
    output: _Output = None,
) -> None:
    """Make a branch sticky for the current profile (or clear it with --main)."""
    runtime = _runtime_from_ctx(ctx)
    if main == (name is not None):
        _fail(
            runtime,
            ErrorEnvelope(error="pass exactly one of NAME or --main", type=ErrorType.INPUT_ERROR),
        )
    _require_saved_profile(runtime, name)
    if name is None:
        _write_profile_branch(runtime, None)
        print(f"profile {runtime.resolved_profile.name} now works on main", file=sys.stderr)
        return
    with _session(runtime) as client:
        branch = require_ready(get_branch(client, name))
    _use(runtime, branch)


def diff_cmd(ctx: typer.Context, name: _OptionalName = None, output: _Output = None) -> None:
    """List the changes staged in a branch."""
    runtime = _runtime_from_ctx(ctx)
    ref = _target_ref(runtime, name)
    with _session(runtime) as client:
        changes = list_changes(client, get_branch(client, ref))
    if runtime.output_format in (OutputFormat.TABLE, OutputFormat.CSV):
        _emit(runtime, [_diff_row(c) for c in changes], _DIFF_COLUMNS)
    else:
        _emit(runtime, changes)


_COMMANDS: list[tuple[str, Callable[..., None]]] = [
    ("list", list_cmd),
    ("show", show_cmd),
    ("current", current_cmd),
    ("create", create_cmd),
    ("use", use_cmd),
    ("diff", diff_cmd),
]


def register(app: typer.Typer) -> None:
    branch_app = typer.Typer(
        name="branch",
        help="NetBox Branching: stage changes in a branch, review, merge.",
        no_args_is_help=True,
    )
    for name, fn in _COMMANDS:
        branch_app.command(name)(fn)
    app.add_typer(branch_app)
