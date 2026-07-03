"""Tests for `nsc.schema.source` — schema-source resolution chain."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from nsc.cache.store import CacheStore
from nsc.cli.runtime import ResolvedProfile
from nsc.completion.cache_probe import load_cached_model_for_profile
from nsc.config.settings import Paths
from nsc.model.command_model import MODEL_FORMAT_VERSION, CommandModel
from nsc.schema.source import (
    SchemaSourceError,
    resolve_command_model,
)


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


def test_explicit_schema_flag_wins(tmp_path: Path) -> None:
    schema_path = tmp_path / "s.json"
    schema_path.write_text(json.dumps(_minimal_schema_doc()), encoding="utf-8")
    paths = _paths(tmp_path)
    model = resolve_command_model(
        paths=paths,
        profile=_profile(),
        schema_override=str(schema_path),
    )
    assert isinstance(model, CommandModel)
    assert "dcim" in model.tags


@respx.mock
def test_profile_schema_url_used_when_set(tmp_path: Path) -> None:
    respx.get("https://prod.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, json=_minimal_schema_doc())
    )
    paths = _paths(tmp_path)
    model = resolve_command_model(
        paths=paths,
        profile=_profile(schema_url="https://prod.example/api/schema/?format=json"),
        schema_override=None,
    )
    assert "dcim" in model.tags


@respx.mock
def test_derived_schema_url_used_when_profile_has_no_schema_url(tmp_path: Path) -> None:
    respx.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, json=_minimal_schema_doc())
    )
    paths = _paths(tmp_path)
    model = resolve_command_model(
        paths=paths,
        profile=_profile(url="https://nb.example/"),
        schema_override=None,
    )
    assert "dcim" in model.tags


@respx.mock
def test_cache_hit_skips_rebuild(tmp_path: Path) -> None:
    route = respx.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, json=_minimal_schema_doc())
    )
    paths = _paths(tmp_path)
    profile = _profile()
    first = resolve_command_model(paths=paths, profile=profile, schema_override=None)
    second = resolve_command_model(paths=paths, profile=profile, schema_override=None)
    assert first.schema_hash == second.schema_hash
    assert route.call_count == 2  # we always re-fetch to compare hash


@respx.mock
def test_offline_falls_back_to_cache_when_present(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    route = respx.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, json=_minimal_schema_doc())
    )
    paths = _paths(tmp_path)
    profile = _profile()
    resolve_command_model(paths=paths, profile=profile, schema_override=None)
    capsys.readouterr()  # drain

    route.mock(side_effect=httpx.ConnectError("offline"))
    model = resolve_command_model(paths=paths, profile=profile, schema_override=None)
    assert isinstance(model, CommandModel)
    err = capsys.readouterr().err
    assert "cached" in err.lower()


@respx.mock
def test_offline_no_cache_falls_back_to_bundled(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.get("https://nb.example/api/schema/?format=json").mock(
        side_effect=httpx.ConnectError("offline")
    )
    paths = _paths(tmp_path)
    profile = _profile()
    model = resolve_command_model(paths=paths, profile=profile, schema_override=None)
    assert isinstance(model, CommandModel)
    err = capsys.readouterr().err
    assert "bundled" in err.lower()


def _stale_the_only_cache_entry(paths: Paths, profile_name: str) -> str:
    """Downgrade the single cached entry to a pre-versioning format so
    `CacheStore.load` rejects it purely on `format_version`. Returns its hash."""
    profile_dir = paths.cache_dir / profile_name
    cache_files = [p for p in profile_dir.glob("*.json") if not p.name.endswith(".meta.json")]
    assert len(cache_files) == 1
    stale_file = cache_files[0]
    data = json.loads(stale_file.read_text())
    data["format_version"] = 0
    stale_file.write_text(json.dumps(data))
    return stale_file.stem


@respx.mock
def test_offline_format_stale_cache_persists_bundled_fallback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Issue #140: when the only cached entry is format-stale (hash-fresh) and
    NetBox is unreachable, the bundled fallback is persisted under the profile
    so the next invocation skips the per-call rebuild — without a fetch
    timestamp, so the TTL fast-path still refetches once NetBox returns."""
    route = respx.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, json=_minimal_schema_doc())
    )
    paths = _paths(tmp_path)
    profile = _profile()
    resolve_command_model(paths=paths, profile=profile, schema_override=None)
    stale_hash = _stale_the_only_cache_entry(paths, "prod")
    capsys.readouterr()  # drain

    route.mock(side_effect=httpx.ConnectError("offline"))
    first = resolve_command_model(paths=paths, profile=profile, schema_override=None)
    assert first.format_version == MODEL_FORMAT_VERSION
    assert "bundled" in capsys.readouterr().err.lower()

    # The bundled model is now persisted under the profile (a distinct hash),
    # carries no fetch timestamp, and is visible to completion — no blackout.
    store = CacheStore(root=paths.cache_dir)
    assert first.schema_hash != stale_hash
    assert store.load("prod", first.schema_hash) is not None
    assert store.load_fetched_at("prod", first.schema_hash) is None
    probed = load_cached_model_for_profile(paths, "prod")
    assert probed is not None
    assert probed.format_version == MODEL_FORMAT_VERSION

    # Second offline invocation hits `_find_any_cached` instead of rebuilding.
    second = resolve_command_model(paths=paths, profile=profile, schema_override=None)
    assert second.schema_hash == first.schema_hash
    assert "cached" in capsys.readouterr().err.lower()


@respx.mock
def test_offline_bundled_fallback_survives_unpersistable_profile_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A profile name outside `_PROFILE_RE` (names aren't validated at config
    time) makes `CacheStore.save` raise `ValueError`; the offline bundled
    fallback must swallow it and still return the in-memory model."""
    respx.get("https://nb.example/api/schema/?format=json").mock(
        side_effect=httpx.ConnectError("offline")
    )
    paths = _paths(tmp_path)
    model = resolve_command_model(
        paths=paths, profile=_profile(name="has space"), schema_override=None
    )
    assert isinstance(model, CommandModel)
    assert "bundled" in capsys.readouterr().err.lower()


@respx.mock
def test_offline_no_cache_no_bundled_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    respx.get("https://nb.example/api/schema/?format=json").mock(
        side_effect=httpx.ConnectError("offline")
    )
    paths = _paths(tmp_path)
    profile = _profile()
    from nsc.schema import source as source_mod  # noqa: PLC0415

    monkeypatch.setattr(source_mod, "_load_bundled_command_model", lambda: None)
    with pytest.raises(SchemaSourceError):
        resolve_command_model(paths=paths, profile=profile, schema_override=None)
