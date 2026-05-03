"""`nsc profiles` — list / add / remove / rename / set-default.

Operates on the same `~/.nsc/config.yaml` as `nsc config` and the same on-disk
cache as the dynamic-tree handlers. `add` runs `verify()` before persisting;
`remove` purges the cache; `rename` moves the cache directory.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from ruamel.yaml.comments import CommentedMap

from nsc.auth.verify import VerifyError, verify
from nsc.cache.store import CacheStore
from nsc.cli.runtime import emit_envelope
from nsc.config.loader import ConfigParseError, load_config
from nsc.config.models import OutputFormat, Profile
from nsc.config.settings import default_paths
from nsc.config.writer import (
    acquire_lock,
    atomic_write,
    dump_round_trip,
    load_round_trip,
)
from nsc.output.errors import ErrorEnvelope, ErrorType


def _config_path() -> Path:
    return default_paths().config_file


def _cache() -> CacheStore:
    return CacheStore(root=default_paths().cache_dir)


def _emit_auth_envelope(
    message: str, *, status_code: int | None, user_check_status: int | None
) -> int:
    details: dict[str, object] = {"reason": "rejected"}
    if user_check_status is not None:
        details["user_check_status"] = user_check_status
    env = ErrorEnvelope(
        error=message,
        type=ErrorType.AUTH,
        status_code=status_code,
        details=details,
    )
    return emit_envelope(env, output_format=OutputFormat.TABLE)


def _emit_config_envelope(message: str) -> int:
    env = ErrorEnvelope(error=message, type=ErrorType.CONFIG)
    return emit_envelope(env, output_format=OutputFormat.TABLE)


def register(app: typer.Typer) -> None:
    profiles_app = typer.Typer(
        name="profiles",
        help="Manage profiles in ~/.nsc/config.yaml.",
        no_args_is_help=True,
    )

    @profiles_app.command("list")
    def list_cmd(
        output: str = typer.Option("table", "--output", "-o", help="table|json"),
    ) -> None:
        _do_list(output)

    @profiles_app.command("add")
    def add_cmd(
        name: str = typer.Argument(...),
        url: str = typer.Option(..., "--url"),
        token: str = typer.Option(..., "--token"),
    ) -> None:
        _do_add(name, url, token)

    @profiles_app.command("remove")
    def remove_cmd(
        name: str = typer.Argument(...),
        force: bool = typer.Option(False, "--force"),
    ) -> None:
        _do_remove(name, force=force)

    @profiles_app.command("rename")
    def rename_cmd(
        old: str = typer.Argument(...),
        new: str = typer.Argument(...),
    ) -> None:
        _do_rename(old, new)

    @profiles_app.command("set-default")
    def set_default_cmd(name: str = typer.Argument(...)) -> None:
        _do_set_default(name)

    app.add_typer(profiles_app)


def _load_doc() -> CommentedMap:
    path = _config_path()
    doc = load_round_trip(path)
    if "profiles" not in doc:
        doc["profiles"] = CommentedMap()
    return doc


def _do_list(output: str) -> None:
    try:
        config = load_config(_config_path())
    except ConfigParseError as exc:
        code = _emit_config_envelope(str(exc))
        raise typer.Exit(code=code) from exc

    if output == "json":
        payload = {
            "default": config.default_profile,
            "profiles": [{"name": p.name, "url": str(p.url)} for p in config.profiles.values()],
        }
        typer.echo(json.dumps(payload, indent=2))
        return

    if not config.profiles:
        typer.echo("(no profiles configured)")
        return
    for name, profile in config.profiles.items():
        marker = "*" if name == config.default_profile else " "
        typer.echo(f"{marker} {name}\t{profile.url}")


def _do_add(name: str, url: str, token: str) -> None:
    path = _config_path()
    try:
        existing = load_config(path)
    except ConfigParseError:
        existing = None
    if existing and name in existing.profiles:
        code = _emit_config_envelope(
            f"profile {name!r} already exists; use `nsc login --rotate --profile {name}` "
            f"to replace its token."
        )
        raise typer.Exit(code=code)

    candidate = Profile(name=name, url=url, token=token)  # type: ignore[arg-type]
    try:
        result = verify(candidate)
    except VerifyError as exc:
        code = _emit_auth_envelope(
            str(exc),
            status_code=exc.status_code,
            user_check_status=exc.user_check_status,
        )
        raise typer.Exit(code=code) from exc

    with acquire_lock(path):
        doc = _load_doc()
        if existing is None or existing.default_profile is None:
            doc.setdefault("default_profile", name)
        profiles = doc["profiles"]
        entry = CommentedMap()
        entry["url"] = url
        entry["token"] = token
        profiles[name] = entry
        atomic_write(path, dump_round_trip(doc))
    typer.echo(f"✓ added profile {name!r}; authenticated as {result.username}")


def _do_remove(name: str, *, force: bool) -> None:
    path = _config_path()
    try:
        config = load_config(path)
    except ConfigParseError as exc:
        code = _emit_config_envelope(str(exc))
        raise typer.Exit(code=code) from exc
    if name not in config.profiles:
        code = _emit_config_envelope(f"profile {name!r} not in config")
        raise typer.Exit(code=code)
    if config.default_profile == name and not force:
        code = _emit_config_envelope(
            f"refusing to remove default profile {name!r}; "
            f"`nsc profiles set-default <other>` first, or pass --force."
        )
        raise typer.Exit(code=code)

    with acquire_lock(path):
        doc = _load_doc()
        profiles = doc.get("profiles") or CommentedMap()
        if name in profiles:
            del profiles[name]
        if doc.get("default_profile") == name:
            del doc["default_profile"]
        atomic_write(path, dump_round_trip(doc))
    _cache().purge(name)
    typer.echo(f"✓ removed profile {name!r}")


def _do_rename(old: str, new: str) -> None:
    path = _config_path()
    try:
        config = load_config(path)
    except ConfigParseError as exc:
        code = _emit_config_envelope(str(exc))
        raise typer.Exit(code=code) from exc
    if old not in config.profiles:
        code = _emit_config_envelope(f"profile {old!r} not in config")
        raise typer.Exit(code=code)
    if new in config.profiles:
        code = _emit_config_envelope(f"profile {new!r} already exists")
        raise typer.Exit(code=code)

    with acquire_lock(path):
        doc = _load_doc()
        profiles = doc["profiles"]
        new_profiles = CommentedMap()
        for k, v in profiles.items():
            new_profiles[new if k == old else k] = v
        doc["profiles"] = new_profiles
        if doc.get("default_profile") == old:
            doc["default_profile"] = new
        atomic_write(path, dump_round_trip(doc))
    try:
        _cache().move(old, new)
    except FileExistsError as exc:
        typer.echo(
            f"warning: cache for {new!r} already exists ({exc}); skipping cache move",
            err=True,
        )
    typer.echo(f"✓ renamed profile {old!r} → {new!r}")


def _do_set_default(name: str) -> None:
    path = _config_path()
    try:
        config = load_config(path)
    except ConfigParseError as exc:
        code = _emit_config_envelope(str(exc))
        raise typer.Exit(code=code) from exc
    if name not in config.profiles:
        code = _emit_config_envelope(f"profile {name!r} not in config")
        raise typer.Exit(code=code)
    with acquire_lock(path):
        doc = _load_doc()
        doc["default_profile"] = name
        atomic_write(path, dump_round_trip(doc))
    typer.echo(f"✓ default_profile = {name}")
