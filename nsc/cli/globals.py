"""Global option definitions and the RuntimeContext factory."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from nsc.cli.runtime import (
    CLIOverrides,
    RuntimeContext,
    resolve_profile,
)
from nsc.config import default_paths
from nsc.config.models import Config
from nsc.http.client import NetBoxClient
from nsc.output.render import select_format
from nsc.schema.source import resolve_command_model


@dataclass
class GlobalState:
    overrides: CLIOverrides
    config: Config
    debug: bool


def build_runtime_context(state: GlobalState) -> RuntimeContext:
    profile = resolve_profile(state.config, state.overrides, env=os.environ)
    paths = default_paths()
    model = resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=state.overrides.schema_override,
        schema_refresh=state.config.defaults.schema_refresh,
        force_refresh=state.overrides.refresh_schema,
    )
    output = select_format(
        cli_value=state.overrides.output,
        env_value=os.environ.get("NSC_OUTPUT"),
        is_tty=sys.stdout.isatty(),
        default=state.config.defaults.output,
    )
    client = NetBoxClient(profile, debug=state.debug)  # type: ignore[arg-type]
    return RuntimeContext(
        resolved_profile=profile,
        config=state.config,
        command_model=model,
        client=client,
        output_format=output,
        debug=state.debug,
        page_size=state.config.defaults.page_size,
    )


__all__ = [
    "GlobalState",
    "build_runtime_context",
]
