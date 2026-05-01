from __future__ import annotations

import gzip
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from typer.testing import CliRunner

from nsc.cli.app import app


@pytest.fixture(autouse=True)
def _bundled_schema_for_runtime(
    monkeypatch: pytest.MonkeyPatch, fixture_profile_yaml: Path
) -> None:
    monkeypatch.setenv("NSC_HOME", str(fixture_profile_yaml))


def _mock_schema(respx_mock: Any) -> None:
    bundled = next(Path("nsc/schemas/bundled").glob("*.json*"))
    if bundled.name.endswith(".gz"):
        body = gzip.decompress(bundled.read_bytes())
    else:
        body = bundled.read_bytes()
    respx_mock.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, content=body, headers={"content-type": "application/json"})
    )


@respx.mock
def test_list_devices_paginates_via_all(
    fixture_response: Callable[[str], dict[str, Any]],
) -> None:
    _mock_schema(respx.mock)
    respx.get("https://nb.example/api/dcim/devices/", params={"cursor": "p2"}).mock(
        return_value=httpx.Response(200, json=fixture_response("dcim_devices_list_p2.json"))
    )
    respx.get("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(200, json=fixture_response("dcim_devices_list_p1.json"))
    )
    result = CliRunner().invoke(app, ["dcim", "devices", "list", "--all", "--output", "json"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    parsed = json.loads(result.stdout)
    assert [r["id"] for r in parsed] == [1, 2, 3]


@respx.mock
def test_list_devices_with_filter_passes_query_param(
    fixture_response: Callable[[str], dict[str, Any]],
) -> None:
    _mock_schema(respx.mock)
    route = respx.get("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(200, json=fixture_response("dcim_devices_list_p2.json"))
    )
    result = CliRunner().invoke(
        app,
        ["dcim", "devices", "list", "--filter", "site_id=42", "--output", "json"],
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    sent = dict(route.calls.last.request.url.params)
    assert sent.get("site_id") == "42"


@respx.mock
def test_get_device_renders_single_object(
    fixture_response: Callable[[str], dict[str, Any]],
) -> None:
    _mock_schema(respx.mock)
    respx.get("https://nb.example/api/dcim/devices/7/").mock(
        return_value=httpx.Response(200, json=fixture_response("dcim_devices_get.json"))
    )
    result = CliRunner().invoke(app, ["dcim", "devices", "get", "7", "--output", "json"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert json.loads(result.stdout)["id"] == 7


@respx.mock
def test_circuits_providers_list_csv(
    fixture_response: Callable[[str], dict[str, Any]],
) -> None:
    _mock_schema(respx.mock)
    respx.get("https://nb.example/api/circuits/providers/").mock(
        return_value=httpx.Response(200, json=fixture_response("circuits_providers_list.json"))
    )
    result = CliRunner().invoke(app, ["circuits", "providers", "list", "--all", "--output", "csv"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert "id" in result.stdout
    assert "Acme" in result.stdout


@respx.mock
def test_401_response_exits_one_with_helpful_error(
    fixture_response: Callable[[str], dict[str, Any]],
) -> None:
    _mock_schema(respx.mock)
    respx.get("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(401, json=fixture_response("auth_401.json"))
    )
    result = CliRunner().invoke(app, ["dcim", "devices", "list", "--output", "json"])
    assert result.exit_code == 1
    combined = (result.stdout or "") + (result.stderr or "")
    assert "401" in combined
    assert "Invalid token" in combined


@respx.mock
def test_piped_stdout_falls_back_to_json(
    fixture_response: Callable[[str], dict[str, Any]],
) -> None:
    _mock_schema(respx.mock)
    respx.get("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(200, json=fixture_response("dcim_devices_list_p2.json"))
    )
    result = CliRunner().invoke(app, ["dcim", "devices", "list"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, list)
