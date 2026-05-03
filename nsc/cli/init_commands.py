"""`nsc init` — first-run wizard.

Prompts for a profile name, URL, and token storage mode, then writes a minimal
`~/.nsc/config.yaml`. Refuses to clobber an existing non-empty config (spec §4.2);
the user should `nsc login --new --profile <name>` to add a profile to an
existing config instead.

`init` is offline-safe: it does not call `verify()` — that is `login`'s job.
"""

from __future__ import annotations

from pathlib import Path

import typer
from ruamel.yaml.comments import CommentedMap, TaggedScalar

from nsc.config.settings import default_paths
from nsc.config.writer import (
    acquire_lock,
    atomic_write,
    dump_round_trip,
    load_round_trip,
)


def _config_path() -> Path:
    return default_paths().config_file


def _build_doc(
    profile_name: str,
    url: str,
    token_value: object,
) -> CommentedMap:
    """Produce the minimal config doc for a fresh init run."""
    profiles = CommentedMap()
    profile = CommentedMap()
    profile["url"] = url
    profile["token"] = token_value
    profiles[profile_name] = profile

    doc = CommentedMap()
    doc["default_profile"] = profile_name
    doc["profiles"] = profiles
    return doc


def _env_tagged(var_name: str) -> object:
    """Build a `!env <VARNAME>` scalar that ruamel will emit with its tag intact."""
    return TaggedScalar(value=var_name, style=None, tag="!env")


def register(app: typer.Typer) -> None:
    @app.command("init", help="First-run wizard — create ~/.nsc/config.yaml.")
    def init_cmd() -> None:
        path = _config_path()
        if path.exists():
            existing = load_round_trip(path)
            if len(existing) > 0:
                typer.echo(
                    f"error: config already exists at {path}; "
                    f"use `nsc login --new` to add a profile.",
                    err=True,
                )
                raise typer.Exit(code=12)

        profile_name = typer.prompt("Profile name", default="default")
        url = typer.prompt("NetBox URL (e.g. https://netbox.example.com/)")
        storage = typer.prompt("Token storage [plaintext|env]", default="plaintext").strip().lower()
        token_value: object
        if storage == "env":
            var_name = typer.prompt("Environment variable name (e.g. NSC_PROD_TOKEN)")
            token_value = _env_tagged(var_name.strip())
        else:
            token_value = typer.prompt("Token", hide_input=True)

        doc = _build_doc(profile_name.strip(), url.strip(), token_value)

        with acquire_lock(path):
            atomic_write(path, dump_round_trip(doc))

        typer.echo(f"wrote {path}")
        typer.echo(f"next: nsc login --profile {profile_name.strip()}")
