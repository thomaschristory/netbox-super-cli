"""Schema-source resolution chain (Phase 2).

Order:
  1. --schema flag (path or URL)
  2. profile.schema_url
  3. {profile.url}/api/schema/?format=json
  4. cache hit (matched by profile name + schema hash)
  5. bundled fallback
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

from nsc.builder.build import build_command_model
from nsc.cache.store import CacheStore
from nsc.cli.runtime import ResolvedProfile
from nsc.config.settings import Paths
from nsc.model.command_model import CommandModel
from nsc.schema.hashing import canonical_sha256
from nsc.schema.loader import LoadedSchema, load_schema
from nsc.schema.models import OpenAPIDocument
from nsc.schemas import bundled as _bundled_pkg


class SchemaSourceError(Exception):
    """Raised when no schema source could be resolved."""


def resolve_command_model(
    *,
    paths: Paths,
    profile: ResolvedProfile,
    schema_override: str | None,
) -> CommandModel:
    if schema_override is not None:
        loaded = load_schema(
            schema_override, verify_ssl=profile.verify_ssl, timeout=profile.timeout
        )
        return _build_and_cache(loaded, paths, profile)

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
        return cached
    model = build_command_model(loaded)
    store.save(profile.name, model)
    return model


def _find_any_cached(paths: Paths, profile_name: str) -> CommandModel | None:
    profile_dir = paths.cache_dir / profile_name
    if not profile_dir.exists():
        return None
    candidates = sorted(
        profile_dir.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        try:
            return CommandModel.model_validate_json(candidate.read_text())
        except Exception:
            continue
    return None


def _load_bundled_command_model() -> CommandModel | None:
    pkg_dir = Path(_bundled_pkg.__file__).resolve().parent
    candidates = sorted(list(pkg_dir.glob("*.json")) + list(pkg_dir.glob("*.json.gz")))
    if not candidates:
        return None
    loaded = load_schema(str(candidates[0]))
    return build_command_model(loaded)
