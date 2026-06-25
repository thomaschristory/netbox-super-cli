"""Typer/Click `shell_complete` adapters.

Wraps the framework-free `providers` with the cheap on-disk `cache_probe`.
Callbacks return plain `list[str]`; Typer's vendored click wraps each into a
`CompletionItem`. Returning strings (not `CompletionItem`) keeps this module
free of any `click` import — typer >= 0.26 vendors its own click, so importing
the standalone `click.shell_completion` here would be a coupling hazard (see
the `#82` note in `nsc/cli/app.py`).

Every public function swallows exceptions and degrades to `[]`: a raised
exception during completion would corrupt the user's shell prompt.

Imports are kept lazy/cheap — no `nsc.cli`, no httpx — so loading this module
never drags in the full app cold-start path.
"""

from __future__ import annotations

import os
import warnings
from typing import Any

from nsc.completion import providers
from nsc.completion.cache_probe import load_cached_model_for_profile, resolve_completion_profile
from nsc.config.loader import ConfigParseError, load_config
from nsc.config.settings import default_paths
from nsc.model.command_model import CommandModel

# Typer >= 0.12 deprecates `shell_complete=` in favour of `autocompletion=`, and
# emits this DeprecationWarning every time it builds a Click param that uses it —
# i.e. on EVERY normal invocation, hundreds of times across the test suite, and
# under `-W error::DeprecationWarning` it would turn even `nsc ls --help` into a
# crash. We cannot migrate to `autocompletion=` yet: Typer's `autocompletion`
# shim discards the Click `ctx` that our resource-name callbacks need to recover
# the active `--profile` from argv, so the dynamic completion would lose its
# profile context. This filter is narrowly scoped to Typer's exact message (not
# a blanket DeprecationWarning suppression). Revisit when Typer exposes a
# ctx-aware completion hook and we can drop `shell_complete=`.
# This module is imported by every site that registers a `shell_complete=`
# param (`nsc.cli.app` and `nsc.cli.aliases_commands`), so registering the
# filter here keeps it localized to the completion concern.
warnings.filterwarnings(
    "ignore",
    message=r".*only the parameter 'autocompletion' is supported.*",
    category=DeprecationWarning,
)


def _active_model(args: list[str]) -> CommandModel | None:
    """Load the cached model for the profile implied by argv/env/config.
    Falls back to the sole cache directory when nothing pins a profile."""
    paths = default_paths()
    try:
        config = load_config(paths.config_file)
    except (ConfigParseError, OSError):
        config = None
    profile: str | None = None
    if config is not None:
        profile = resolve_completion_profile(config, args=args, env=dict(os.environ))
    if profile is None:
        dirs = providers.cache_dir_profile_names(paths)
        if len(dirs) == 1:
            profile = dirs[0]
    if profile is None:
        return None
    return load_cached_model_for_profile(paths, profile)


def complete_resource_name(verb: str, *, incomplete: str) -> list[str]:
    try:
        model = _active_model([])
        return providers.resource_name_candidates(model, verb=verb, incomplete=incomplete)
    except Exception:
        return []


def complete_profile(*, incomplete: str) -> list[str]:
    try:
        return providers.profile_candidates(default_paths(), incomplete=incomplete)
    except Exception:
        return []


def _shell_args(ctx: Any) -> list[str]:
    """Best-effort recovery of the raw argv Click saw, used to honour a
    `--profile` passed earlier on the same line."""
    try:
        params = getattr(ctx, "params", None)
        if isinstance(params, dict):
            value = params.get("profile")
            if isinstance(value, str):
                return ["--profile", value]
    except Exception:
        pass
    return []


def shell_complete_resource_name_ls(ctx: Any, param: Any, incomplete: str) -> list[str]:
    return _resource_shell_complete("ls", ctx, incomplete)


def shell_complete_resource_name_get(ctx: Any, param: Any, incomplete: str) -> list[str]:
    return _resource_shell_complete("get", ctx, incomplete)


def shell_complete_resource_name_rm(ctx: Any, param: Any, incomplete: str) -> list[str]:
    return _resource_shell_complete("rm", ctx, incomplete)


def _resource_shell_complete(verb: str, ctx: Any, incomplete: str) -> list[str]:
    try:
        model = _active_model(_shell_args(ctx))
        return providers.resource_name_candidates(model, verb=verb, incomplete=incomplete)
    except Exception:
        return []


def shell_complete_profile(ctx: Any, param: Any, incomplete: str) -> list[str]:
    return complete_profile(incomplete=incomplete)
