"""Schema-source resolution chain.

Order, given a `schema_refresh` policy and an optional `force_refresh`:
  1. --schema flag (path or URL) — always wins, never consults TTL.
  2. TTL fast-path: if `schema_refresh` allows it and a cache entry for
     this profile is fresher than the policy's TTL, return it directly
     without any HTTP roundtrip. Skipped when `force_refresh=True`.
  3. Network fetch from `profile.schema_url` or `{profile.url}/api/schema/`.
  4. On fetch failure: any cached entry, then bundled fallback.

Issue #34: prior to the TTL fast-path the schema was fetched on every
invocation (one extra round-trip per command), which is visible in NetBox
access logs as a `GET /api/schema/` between every PATCH.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx
from ruamel.yaml import YAML

from nsc.builder.build import build_command_model
from nsc.cache.store import CacheStore
from nsc.cli.runtime import ResolvedProfile
from nsc.config.models import SchemaRefresh
from nsc.config.settings import Paths
from nsc.model.command_model import CommandModel
from nsc.schema.hashing import canonical_sha256
from nsc.schema.loader import LoadedSchema, load_schema
from nsc.schema.models import OpenAPIDocument
from nsc.schemas import bundled as _bundled_pkg

_DAILY_SECONDS = 86_400.0
_WEEKLY_SECONDS = 604_800.0


class SchemaSourceError(Exception):
    """Raised when no schema source could be resolved."""


def _ttl_for_policy(policy: SchemaRefresh) -> float:
    """How long a cache entry stays trusted under each refresh policy.

    `0` means "never trust the cache without re-fetching" (the legacy
    `on-hash-change` behaviour). `inf` means "trust the cache forever"
    (manual — the user is responsible for refreshing)."""
    match policy:
        case SchemaRefresh.MANUAL:
            return float("inf")
        case SchemaRefresh.DAILY:
            return _DAILY_SECONDS
        case SchemaRefresh.WEEKLY:
            return _WEEKLY_SECONDS
        case SchemaRefresh.ON_HASH_CHANGE:
            return 0.0


def resolve_command_model(
    *,
    paths: Paths,
    profile: ResolvedProfile,
    schema_override: str | None,
    schema_refresh: SchemaRefresh = SchemaRefresh.ON_HASH_CHANGE,
    force_refresh: bool = False,
) -> CommandModel:
    if schema_override is not None:
        loaded = load_schema(
            schema_override, verify_ssl=profile.verify_ssl, timeout=profile.timeout
        )
        return _build_and_cache(loaded, paths, profile)

    if not force_refresh:
        ttl = _ttl_for_policy(schema_refresh)
        if ttl > 0:
            fresh = _find_fresh_cached(paths, profile.name, ttl_seconds=ttl)
            if fresh is not None:
                return fresh

    schema_url = (
        str(profile.schema_url)
        if profile.schema_url is not None
        else f"{str(profile.url).rstrip('/')}/api/schema/?format=json"
    )

    try:
        loaded = _fetch_schema(schema_url, profile)
    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
        cached = _find_any_cached(paths, profile.name)
        if cached is not None:
            print(
                f"Could not reach NetBox ({exc}); using cached schema.",
                file=sys.stderr,
            )
            return cached
        bundled = _load_bundled_command_model()
        if bundled is not None:
            print(
                f"Could not reach NetBox ({exc}) and no cache; using bundled schema.",
                file=sys.stderr,
            )
            return bundled
        raise SchemaSourceError(
            f"could not reach NetBox at {schema_url}, no cache, no bundled fallback: {exc}"
        ) from exc

    return _build_and_cache(loaded, paths, profile)


def _fetch_schema(url: str, profile: ResolvedProfile) -> LoadedSchema:
    headers: dict[str, str] = {"Accept": "application/json"}
    if profile.token:
        headers["Authorization"] = f"Token {profile.token}"
    with httpx.Client(verify=profile.verify_ssl, timeout=profile.timeout, headers=headers) as c:
        response = c.get(url)
        response.raise_for_status()
        body = response.content
    document = OpenAPIDocument.model_validate_json(body)
    return LoadedSchema(source=url, body=body, hash=canonical_sha256(body), document=document)


def _build_and_cache(loaded: LoadedSchema, paths: Paths, profile: ResolvedProfile) -> CommandModel:
    store = CacheStore(root=paths.cache_dir)
    cached = store.load(profile.name, loaded.hash)
    if cached is not None:
        # Issue #39: a live fetch just confirmed this hash is current.
        # Bump the sidecar so the TTL fast-path trusts the cache on the
        # next invocation, otherwise an aged-out sidecar (or a legacy
        # cache from before sidecars existed) makes us refetch every
        # invocation even though the schema hasn't moved.
        store.touch_fetched_at(profile.name, loaded.hash)
        return cached
    model = build_command_model(loaded)
    store.save(profile.name, model)
    return model


def _iter_cache_files(profile_dir: Path) -> list[Path]:
    return [p for p in profile_dir.glob("*.json") if not p.name.endswith(".meta.json")]


def _find_any_cached(paths: Paths, profile_name: str) -> CommandModel | None:
    profile_dir = paths.cache_dir / profile_name
    if not profile_dir.exists():
        return None
    store = CacheStore(root=paths.cache_dir)
    candidates = sorted(
        _iter_cache_files(profile_dir),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        model = store.load(profile_name, candidate.stem)
        if model is not None:
            return model
    return None


_CLOCK_SKEW_TOLERANCE_SECONDS = 60.0


def _find_fresh_cached(
    paths: Paths,
    profile_name: str,
    *,
    ttl_seconds: float,
    now: float | None = None,
) -> CommandModel | None:
    """Freshness is keyed off the sidecar — never the cache file's mtime —
    so a `touch`, backup-restore, or `cp -p` cannot fake freshness. A
    sidecar dated more than `_CLOCK_SKEW_TOLERANCE_SECONDS` in the future
    is rejected (likely a clock that jumped forward then back).
    `CacheStore.load` re-verifies `<hash>.json` contents match `<hash>`,
    so a tampered or copied file is rejected."""
    profile_dir = paths.cache_dir / profile_name
    if not profile_dir.exists():
        return None
    now_t = now if now is not None else time.time()
    cutoff = now_t - ttl_seconds
    skew_limit = now_t + _CLOCK_SKEW_TOLERANCE_SECONDS
    store = CacheStore(root=paths.cache_dir)
    fresh: list[tuple[float, str]] = []
    for candidate in _iter_cache_files(profile_dir):
        fetched_at = store.load_fetched_at(profile_name, candidate.stem)
        if fetched_at is None:
            continue
        if fetched_at > skew_limit or fetched_at < cutoff:
            continue
        fresh.append((fetched_at, candidate.stem))
    fresh.sort(reverse=True)
    for _, schema_hash in fresh:
        model = store.load(profile_name, schema_hash)
        if model is not None:
            return model
    return None


def _load_bundled_command_model() -> CommandModel | None:
    pkg_dir = Path(_bundled_pkg.__file__).resolve().parent
    manifest_path = pkg_dir / "manifest.yaml"
    if not manifest_path.exists():
        return None
    manifest = YAML(typ="safe").load(manifest_path.read_text())
    schemas = manifest.get("schemas") if isinstance(manifest, dict) else None
    if not schemas:
        return None
    newest = schemas[-1]
    schema_path = pkg_dir / str(newest["file"])
    if not schema_path.exists():
        return None
    loaded = load_schema(str(schema_path))
    return build_command_model(loaded)
