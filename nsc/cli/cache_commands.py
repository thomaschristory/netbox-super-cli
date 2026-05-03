"""`nsc cache` — local cache management. Phase 5a ships `prune`."""

from __future__ import annotations

import json
from collections.abc import Callable
from enum import StrEnum
from typing import Annotated

import httpx
import typer

from nsc.cache.store import (
    CacheStore,
    PrunePlan,
    PruneResult,
    compute_prune_plan,
    prune_orphans,
)
from nsc.config.loader import ConfigParseError, load_config
from nsc.config.models import Config, Profile
from nsc.config.settings import default_paths
from nsc.schema.hashing import canonical_sha256

_PRUNE_FETCH_TIMEOUT_SECONDS = 5.0
"""Per-profile timeout when fetching the live schema for stale-hash classification.
Deliberately tighter than `Config.defaults.timeout` (30s): cache prune is a fast
cleanup tool, and an unreachable profile must not stall the operation."""


class _OutputFormat(StrEnum):
    TABLE = "table"
    JSON = "json"


def _store() -> CacheStore:
    return CacheStore(root=default_paths().cache_dir)


def _load_config_or_empty() -> Config:
    try:
        return load_config(default_paths().config_file)
    except (FileNotFoundError, ConfigParseError):
        return Config()


def _fetch_live_hash(profile: Profile, *, default_timeout: float) -> str:
    url = str(profile.url).rstrip("/") + "/api/schema/?format=json"
    headers = {"Accept": "application/json"}
    if profile.token:
        headers["Authorization"] = f"Token {profile.token}"
    timeout = profile.timeout if profile.timeout is not None else default_timeout
    with httpx.Client(verify=profile.verify_ssl, timeout=timeout, headers=headers) as c:
        resp = c.get(url)
        resp.raise_for_status()
        return canonical_sha256(resp.content)


def _make_fetcher(default_timeout: float) -> Callable[[Profile], str]:
    def fetcher(profile: Profile) -> str:
        return _fetch_live_hash(profile, default_timeout=default_timeout)

    return fetcher


def _render_table(plan: PrunePlan, mode: str, result: PruneResult | None) -> str:
    lines: list[str] = []
    if mode == "dry-run":
        lines.append("nsc cache prune (dry-run) — pass --apply to delete")
    else:
        lines.append("nsc cache prune (applied)")
    if plan.orphan_profile_dirs:
        lines.append("  orphan profile directories:")
        for d in plan.orphan_profile_dirs:
            lines.append(f"    {d}")
    if plan.stale_hash_files:
        lines.append("  stale-hash files:")
        for f in plan.stale_hash_files:
            lines.append(f"    {f}")
    if plan.aged_files:
        lines.append("  aged-out files:")
        for f in plan.aged_files:
            lines.append(f"    {f}")
    if plan.total_count() == 0:
        lines.append("  nothing to prune")
    if mode == "dry-run":
        lines.append(f"  would free: {plan.total_bytes()} bytes")
    elif result is not None:
        lines.append(
            f"  freed: {result.freed_bytes} bytes "
            f"({result.deleted_dirs} dir(s), {result.deleted_files} file(s))"
        )
    return "\n".join(lines)


def _render_json(plan: PrunePlan, mode: str, result: PruneResult | None) -> str:
    payload: dict[str, object] = {
        "mode": mode,
        "plan": {
            "orphan_profile_dirs": [str(p) for p in plan.orphan_profile_dirs],
            "stale_hash_files": [str(p) for p in plan.stale_hash_files],
            "aged_files": [str(p) for p in plan.aged_files],
            "total_count": plan.total_count(),
        },
    }
    if mode == "dry-run":
        payload["would_free_bytes"] = plan.total_bytes()
    elif result is not None:
        payload["result"] = {
            "deleted_dirs": result.deleted_dirs,
            "deleted_files": result.deleted_files,
            "freed_bytes": result.freed_bytes,
        }
    return json.dumps(payload)


def register(app: typer.Typer) -> None:
    cache_app = typer.Typer(
        name="cache",
        help="Manage the on-disk command-model cache.",
        no_args_is_help=True,
    )

    @cache_app.command("prune")
    def prune_cmd(
        apply_: Annotated[
            bool, typer.Option("--apply", help="Actually delete (default: dry-run).")
        ] = False,
        max_age: Annotated[
            int | None,
            typer.Option(
                "--max-age",
                help="Also prune cache files older than N days.",
                min=1,
            ),
        ] = None,
        output: Annotated[
            _OutputFormat,
            typer.Option("--output", "-o", help="table|json"),
        ] = _OutputFormat.TABLE,
    ) -> None:
        config = _load_config_or_empty()
        store = _store()
        fetcher = _make_fetcher(default_timeout=_PRUNE_FETCH_TIMEOUT_SECONDS)
        plan = compute_prune_plan(
            config=config,
            store=store,
            fetch_live_hash=fetcher,
            max_age_days=max_age,
        )
        mode = "apply" if apply_ else "dry-run"
        result = prune_orphans(plan) if apply_ else None

        if output is _OutputFormat.JSON:
            typer.echo(_render_json(plan, mode, result))
        else:
            typer.echo(_render_table(plan, mode, result))

    app.add_typer(cache_app, name="cache")
