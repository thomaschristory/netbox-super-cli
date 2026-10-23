"""Global option definitions and the RuntimeContext factory."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass

from nsc.branching.resolve import get_branch, require_ready
from nsc.cli.runtime import (
    CLIOverrides,
    RuntimeContext,
    ignored_profile_branch,
    resolve_branch_selection,
    resolve_color,
    resolve_object_colors,
    resolve_profile,
)
from nsc.config import default_paths
from nsc.config.models import Config, ObjectColorMode
from nsc.http.client import NetBoxClient
from nsc.output.render import select_format
from nsc.schema.source import resolve_command_model


@dataclass
class GlobalState:
    overrides: CLIOverrides
    config: Config
    debug: bool


def build_runtime_context(state: GlobalState) -> RuntimeContext:
    # Validate the format before the schema fetch so a typo fails fast and offline.
    output = select_format(
        cli_value=state.overrides.output,
        env_value=os.environ.get("NSC_OUTPUT"),
        is_tty=sys.stdout.isatty(),
        default=state.config.defaults.output,
    )
    profile = resolve_profile(state.config, state.overrides, env=os.environ)
    paths = default_paths()
    model = resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=state.overrides.schema_override,
        schema_refresh=state.config.defaults.schema_refresh,
        force_refresh=state.overrides.refresh_schema,
    )
    branch = resolve_branch_selection(state.config, state.overrides, env=os.environ)
    ignored = ignored_profile_branch(state.config, state.overrides, env=os.environ)
    if ignored is not None and branch is None:
        print(
            f"⎇ profile branch {ignored} ignored: --url/NSC_URL targets another server",
            file=sys.stderr,
        )
    client = NetBoxClient(
        profile,  # type: ignore[arg-type]
        debug=state.debug,
        redaction=state.config.defaults.audit_redaction,
        profile_name=profile.name,
        branch_resolver=_branch_resolver(branch.name) if branch else None,
    )
    if branch is not None:
        print(f"⎇ branch: {branch.name}", file=sys.stderr)
    color = resolve_color(state.config.defaults.color_mode, is_tty=sys.stdout.isatty())
    object_color_mode = _resolve_object_color_mode(state)
    return RuntimeContext(
        resolved_profile=profile,
        branch=branch,
        config=state.config,
        command_model=model,
        client=client,
        output_format=output,
        debug=state.debug,
        page_size=state.config.defaults.page_size,
        color=color,
        color_stderr=resolve_color(state.config.defaults.color_mode, is_tty=sys.stderr.isatty()),
        object_colors=resolve_object_colors(object_color_mode, color=color),
    )


def _branch_resolver(ref: str) -> Callable[[NetBoxClient], str]:
    def resolve(client: NetBoxClient) -> str:
        return require_ready(get_branch(client, ref)).schema_id

    return resolve


def _resolve_object_color_mode(state: GlobalState) -> ObjectColorMode:
    override = state.overrides.object_colors
    if override is None:
        return state.config.defaults.object_colors
    return ObjectColorMode.ON if override else ObjectColorMode.OFF


__all__ = [
    "GlobalState",
    "build_runtime_context",
]
