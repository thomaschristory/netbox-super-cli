"""Integration tests for `nsc ls` alias."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from typer.testing import CliRunner

from nsc.cli.app import app


@pytest.fixture(autouse=True)
def _profile(monkeypatch: pytest.MonkeyPatch, fixture_profile_yaml: Path) -> None:
    monkeypatch.setenv("NSC_HOME", str(fixture_profile_yaml))


def _mock_schema(respx_mock: Any) -> None:
    bundled = next(Path("nsc/schemas/bundled").glob("*.json*"))
    body = (
        gzip.decompress(bundled.read_bytes())
        if bundled.name.endswith(".gz")
        else bundled.read_bytes()
    )
    respx_mock.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, content=body, headers={"content-type": "application/json"})
    )


@respx.mock
def test_ls_devices_invokes_list_endpoint() -> None:
    _mock_schema(respx.mock)
    respx.get("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(
            200, json={"count": 0, "next": None, "previous": None, "results": []}
        )
    )
    result = CliRunner().invoke(app, ["ls", "devices", "--output", "json"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert json.loads(result.stdout) == []


@respx.mock
def test_ls_unknown_resource_exits_14() -> None:
    _mock_schema(respx.mock)
    result = CliRunner().invoke(app, ["ls", "nonexistent", "--output", "json"])
    assert result.exit_code == 14, (result.exit_code, result.stdout)
    payload = json.loads(result.stdout)
    assert payload["type"] == "unknown_alias"
    assert payload["details"]["term"] == "nonexistent"


@respx.mock
def test_ls_passes_filters() -> None:
    _mock_schema(respx.mock)
    route = respx.get("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(
            200, json={"count": 0, "next": None, "previous": None, "results": []}
        )
    )
    CliRunner().invoke(app, ["ls", "devices", "--filter", "site=us-east-1", "--output", "json"])
    assert route.called
    last = route.calls.last.request
    assert "site=us-east-1" in str(last.url)
