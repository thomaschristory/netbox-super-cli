"""Tests for `nsc.schema.source` — schema-source resolution chain."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from nsc.cli.runtime import ResolvedProfile
from nsc.config.settings import Paths
from nsc.model.command_model import CommandModel
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
