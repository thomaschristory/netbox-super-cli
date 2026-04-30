"""Tests for `nsc.schema.loader`."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from nsc.schema.loader import LoadedSchema, SchemaLoadError, load_schema

MINIMAL = {
    "openapi": "3.0.3",
    "info": {"title": "NetBox", "version": "4.1.0"},
    "paths": {},
    "components": {"schemas": {}},
    "tags": [],
}


def test_loads_from_local_file(tmp_path: Path) -> None:
    p = tmp_path / "schema.json"
    p.write_text(json.dumps(MINIMAL))
    loaded = load_schema(str(p))
    assert isinstance(loaded, LoadedSchema)
    assert loaded.document.info.version == "4.1.0"
    assert loaded.source == str(p)
    assert len(loaded.hash) == 64


@respx.mock
def test_loads_from_https_url() -> None:
    url = "https://netbox.example.com/api/schema/?format=json"
    respx.get(url).mock(return_value=httpx.Response(200, json=MINIMAL))
    loaded = load_schema(url)
    assert loaded.document.info.title == "NetBox"
    assert loaded.source == url


def test_missing_file_raises() -> None:
    with pytest.raises(SchemaLoadError, match="not found"):
        load_schema("/no/such/file.json")


def test_non_json_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("not json")
    with pytest.raises(SchemaLoadError, match="not valid JSON"):
        load_schema(str(p))


@respx.mock
def test_http_error_raises_load_error() -> None:
    url = "https://netbox.example.com/api/schema/"
    respx.get(url).mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(SchemaLoadError, match="500"):
        load_schema(url)
