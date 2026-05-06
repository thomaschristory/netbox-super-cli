"""Tests for schema-source TTL fast-path (issue #34).

Verifies that `resolve_command_model` honours the configured
`SchemaRefresh` policy and the `force_refresh` flag, skipping the
`/api/schema/` HTTP roundtrip when a fresh cache entry exists.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from nsc.cli.runtime import ResolvedProfile
from nsc.config.models import SchemaRefresh
from nsc.config.settings import Paths
from nsc.schema.source import resolve_command_model


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
    aged = os.path.getmtime(next(profile_dir.glob("*.json"))) - 2 * 86400
    for f in profile_dir.glob("*.json"):
        os.utime(f, (aged, aged))

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
    very_old = 0.0
    for f in profile_dir.glob("*.json"):
        os.utime(f, (very_old, very_old))

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
