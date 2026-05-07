"""Tests for schema-source TTL fast-path (issue #34).

Verifies that `resolve_command_model` honours the configured
`SchemaRefresh` policy and the `force_refresh` flag, skipping the
`/api/schema/` HTTP roundtrip when a fresh cache entry exists.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from nsc.cli.runtime import ResolvedProfile
from nsc.config.models import SchemaRefresh
from nsc.config.settings import Paths
from nsc.schema.source import resolve_command_model


def _age_sidecars(profile_dir: Path, fetched_at: float) -> None:
    """Rewrite every `<hash>.meta.json` so the fast path treats the entry
    as having been fetched at `fetched_at`."""
    for meta in profile_dir.glob("*.meta.json"):
        meta.write_text(json.dumps({"fetched_at": fetched_at}))


def _profile(**kwargs: Any) -> ResolvedProfile:
    return ResolvedProfile(
        name=kwargs.get("name", "prod"),
        url=kwargs.get("url", "https://nb.example/"),
        token=kwargs.get("token", "tok"),
        verify_ssl=kwargs.get("verify_ssl", True),
        timeout=kwargs.get("timeout", 5.0),
        schema_url=kwargs.get("schema_url"),
    )


def _paths(tmp_path: Path) -> Paths:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    return Paths(root=home)


def _minimal_schema_doc() -> dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1.0.0"},
        "tags": [{"name": "dcim"}],
        "paths": {
            "/api/dcim/devices/": {
                "get": {
                    "operationId": "dcim_devices_list",
                    "tags": ["dcim"],
                    "parameters": [],
                    "responses": {"200": {"description": "ok", "content": {}}},
                }
            }
        },
        "components": {"schemas": {}},
    }


@respx.mock
def test_daily_refresh_skips_fetch_when_cache_is_fresh(tmp_path: Path) -> None:
    """With DAILY policy and a cache entry written seconds ago, the
    second resolve must NOT hit /api/schema/."""
    route = respx.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, json=_minimal_schema_doc())
    )
    paths = _paths(tmp_path)
    profile = _profile()

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.DAILY,
    )
    assert route.call_count == 1

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.DAILY,
    )
    assert route.call_count == 1, "second call must use the fresh cache, not refetch"


@respx.mock
def test_daily_refresh_refetches_when_cache_is_stale(tmp_path: Path) -> None:
    """When the newest cache entry is older than DAILY's TTL (24h),
    we must fetch again."""
    route = respx.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, json=_minimal_schema_doc())
    )
    paths = _paths(tmp_path)
    profile = _profile()

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.DAILY,
    )
    assert route.call_count == 1

    profile_dir = paths.cache_dir / profile.name
    _age_sidecars(profile_dir, time.time() - 2 * 86400)

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.DAILY,
    )
    assert route.call_count == 2


@respx.mock
def test_manual_refresh_uses_cache_indefinitely(tmp_path: Path) -> None:
    """MANUAL means: never auto-refresh — any cache hit wins,
    regardless of age."""
    route = respx.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, json=_minimal_schema_doc())
    )
    paths = _paths(tmp_path)
    profile = _profile()

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.MANUAL,
    )
    assert route.call_count == 1

    profile_dir = paths.cache_dir / profile.name
    _age_sidecars(profile_dir, 0.0)

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.MANUAL,
    )
    assert route.call_count == 1


@respx.mock
def test_force_refresh_bypasses_fresh_cache(tmp_path: Path) -> None:
    """`force_refresh=True` forces a fetch even with a fresh cache."""
    route = respx.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, json=_minimal_schema_doc())
    )
    paths = _paths(tmp_path)
    profile = _profile()

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.DAILY,
    )
    assert route.call_count == 1

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.DAILY,
        force_refresh=True,
    )
    assert route.call_count == 2


@respx.mock
def test_on_hash_change_keeps_legacy_behaviour(tmp_path: Path) -> None:
    """ON_HASH_CHANGE preserves the v1.0.1 behaviour: every invocation
    fetches the live schema to compare hashes."""
    route = respx.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, json=_minimal_schema_doc())
    )
    paths = _paths(tmp_path)
    profile = _profile()

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.ON_HASH_CHANGE,
    )
    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.ON_HASH_CHANGE,
    )
    assert route.call_count == 2


@respx.mock
def test_no_cache_yet_falls_back_to_fetch(tmp_path: Path) -> None:
    """First-ever invocation: no cache exists, must fetch even in
    MANUAL mode (otherwise nothing would work)."""
    route = respx.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, json=_minimal_schema_doc())
    )
    paths = _paths(tmp_path)

    resolve_command_model(
        paths=paths,
        profile=_profile(),
        schema_override=None,
        schema_refresh=SchemaRefresh.MANUAL,
    )
    assert route.call_count == 1


@respx.mock
def test_explicit_schema_override_ignores_ttl(tmp_path: Path) -> None:
    """`--schema <path>` always wins; never consults TTL or hits the
    network."""
    route = respx.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(500)
    )
    schema_path = tmp_path / "s.json"
    schema_path.write_text(json.dumps(_minimal_schema_doc()), encoding="utf-8")
    paths = _paths(tmp_path)

    resolve_command_model(
        paths=paths,
        profile=_profile(),
        schema_override=str(schema_path),
        schema_refresh=SchemaRefresh.DAILY,
    )
    assert route.call_count == 0


def test_default_for_schema_refresh_is_daily() -> None:
    """The `Defaults.schema_refresh` default must be `daily` —
    the fast-path is the new normal (issue #34)."""
    from nsc.config.models import Defaults  # noqa: PLC0415

    assert Defaults().schema_refresh is SchemaRefresh.DAILY


@pytest.mark.parametrize(
    ("policy", "expected_ttl"),
    [
        (SchemaRefresh.MANUAL, float("inf")),
        (SchemaRefresh.DAILY, 86400.0),
        (SchemaRefresh.WEEKLY, 604800.0),
        (SchemaRefresh.ON_HASH_CHANGE, 0.0),
    ],
)
def test_ttl_for_policy(policy: SchemaRefresh, expected_ttl: float) -> None:
    from nsc.schema.source import _ttl_for_policy  # noqa: PLC0415

    assert _ttl_for_policy(policy) == expected_ttl


@respx.mock
def test_missing_sidecar_forces_refetch_under_daily(tmp_path: Path) -> None:
    """A cache file without its `<hash>.meta.json` sidecar is distrusted —
    the fast path can't prove freshness, so we refetch. This is the
    upgrade path for caches written before the sidecar existed."""
    route = respx.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, json=_minimal_schema_doc())
    )
    paths = _paths(tmp_path)
    profile = _profile()

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.DAILY,
    )
    assert route.call_count == 1

    profile_dir = paths.cache_dir / profile.name
    for meta in profile_dir.glob("*.meta.json"):
        meta.unlink()

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.DAILY,
    )
    assert route.call_count == 2


@respx.mock
def test_future_dated_sidecar_is_rejected(tmp_path: Path) -> None:
    """A `fetched_at` more than a minute in the future (clock skew or
    tampering) is treated as stale and forces a refetch."""
    route = respx.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, json=_minimal_schema_doc())
    )
    paths = _paths(tmp_path)
    profile = _profile()

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.DAILY,
    )
    assert route.call_count == 1

    profile_dir = paths.cache_dir / profile.name
    _age_sidecars(profile_dir, time.time() + 3600)

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.DAILY,
    )
    assert route.call_count == 2


@respx.mock
def test_fast_path_rejects_hash_mismatch(tmp_path: Path) -> None:
    """If a cache file's contents claim a different schema_hash than its
    filename, the fast path must reject it (`CacheStore.load` already
    enforces this — verify the fast path actually routes through it)."""
    route = respx.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, json=_minimal_schema_doc())
    )
    paths = _paths(tmp_path)
    profile = _profile()

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.DAILY,
    )
    assert route.call_count == 1

    profile_dir = paths.cache_dir / profile.name
    cache_file = next(p for p in profile_dir.glob("*.json") if not p.name.endswith(".meta.json"))
    payload = json.loads(cache_file.read_text())
    payload["schema_hash"] = "f" * 64
    cache_file.write_text(json.dumps(payload))

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.DAILY,
    )
    assert route.call_count == 2


@respx.mock
def test_legacy_cache_without_sidecar_warms_then_uses_fast_path(tmp_path: Path) -> None:
    """Issue #39: a cache file written by a pre-#35 version has no
    sidecar. The first invocation under DAILY must fetch (sidecar
    missing → no proof of freshness), confirm the live hash matches the
    legacy file, write a sidecar, and the second invocation must hit
    the fast path. Without this self-healing the user sees a fresh
    `/api/schema/` request on every command."""
    route = respx.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, json=_minimal_schema_doc())
    )
    paths = _paths(tmp_path)
    profile = _profile()

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.DAILY,
    )
    assert route.call_count == 1

    profile_dir = paths.cache_dir / profile.name
    for meta in profile_dir.glob("*.meta.json"):
        meta.unlink()

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.DAILY,
    )
    assert route.call_count == 2

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.DAILY,
    )
    assert route.call_count == 2, (
        "after the first warm-up the sidecar must exist, so the next "
        "call goes through the fast path"
    )


@respx.mock
def test_aged_cache_with_unchanged_hash_refreshes_sidecar(tmp_path: Path) -> None:
    """Issue #39: when the cache has aged past the TTL but the live
    schema hash is unchanged, `_build_and_cache` finds the cache hit by
    hash. It must still bump `fetched_at` so the next invocation can
    skip the network — otherwise every subsequent call refetches even
    though the schema hasn't moved."""
    route = respx.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, json=_minimal_schema_doc())
    )
    paths = _paths(tmp_path)
    profile = _profile()

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.DAILY,
    )
    assert route.call_count == 1

    profile_dir = paths.cache_dir / profile.name
    _age_sidecars(profile_dir, time.time() - 2 * 86400)

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.DAILY,
    )
    assert route.call_count == 2

    resolve_command_model(
        paths=paths,
        profile=profile,
        schema_override=None,
        schema_refresh=SchemaRefresh.DAILY,
    )
    assert route.call_count == 2, (
        "the second resolve refreshed the sidecar, so the third must use the fast path"
    )
