from __future__ import annotations

import gzip
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest
import respx
from typer.testing import CliRunner

from nsc.cli.app import app
from nsc.output.errors import EXIT_CODES, ErrorType


@pytest.fixture(autouse=True)
def _bundled_schema_for_runtime(
    monkeypatch: pytest.MonkeyPatch, fixture_profile_yaml: Path
) -> None:
    monkeypatch.setenv("NSC_HOME", str(fixture_profile_yaml))


def _mock_schema(respx_mock: respx.Router) -> None:
    bundled = next(Path("nsc/schemas/bundled").glob("*.json*"))
    if bundled.name.endswith(".gz"):
        body = gzip.decompress(bundled.read_bytes())
    else:
        body = bundled.read_bytes()
    respx_mock.get("https://nb.example/api/schema/?format=json").respond(
        200, content=body, headers={"content-type": "application/json"}
    )


def test_list_devices_paginates_via_all(
    fixture_response: Callable[[str], dict[str, Any]],
    httpx2_mock: respx.Router,
) -> None:
    _mock_schema(httpx2_mock)
    httpx2_mock.get("https://nb.example/api/dcim/devices/", params={"cursor": "p2"}).respond(
        200, json=fixture_response("dcim_devices_list_p2.json")
    )
    httpx2_mock.get("https://nb.example/api/dcim/devices/").respond(
        200, json=fixture_response("dcim_devices_list_p1.json")
    )
    result = CliRunner().invoke(app, ["dcim", "devices", "list", "--all", "--output", "json"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    parsed = json.loads(result.stdout)
    assert [r["id"] for r in parsed] == [1, 2, 3]


def test_list_devices_with_filter_passes_query_param(
    fixture_response: Callable[[str], dict[str, Any]],
    httpx2_mock: respx.Router,
) -> None:
    _mock_schema(httpx2_mock)
    route = httpx2_mock.get("https://nb.example/api/dcim/devices/").respond(
        200, json=fixture_response("dcim_devices_list_p2.json")
    )
    result = CliRunner().invoke(
        app,
        ["dcim", "devices", "list", "--filter", "site_id=42", "--output", "json"],
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    sent = dict(route.calls.last.request.url.params)
    assert sent.get("site_id") == "42"


def test_get_device_renders_single_object(
    fixture_response: Callable[[str], dict[str, Any]],
    httpx2_mock: respx.Router,
) -> None:
    _mock_schema(httpx2_mock)
    httpx2_mock.get("https://nb.example/api/dcim/devices/7/").respond(
        200, json=fixture_response("dcim_devices_get.json")
    )
    result = CliRunner().invoke(app, ["dcim", "devices", "get", "7", "--output", "json"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert json.loads(result.stdout)["id"] == 7


def test_circuits_providers_list_csv(
    fixture_response: Callable[[str], dict[str, Any]],
    httpx2_mock: respx.Router,
) -> None:
    _mock_schema(httpx2_mock)
    httpx2_mock.get("https://nb.example/api/circuits/providers/").respond(
        200, json=fixture_response("circuits_providers_list.json")
    )
    result = CliRunner().invoke(app, ["circuits", "providers", "list", "--all", "--output", "csv"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert "id" in result.stdout
    assert "Acme" in result.stdout


def test_401_response_emits_auth_envelope(
    fixture_response: Callable[[str], dict[str, Any]],
    httpx2_mock: respx.Router,
) -> None:
    _mock_schema(httpx2_mock)
    httpx2_mock.get("https://nb.example/api/dcim/devices/").respond(
        401, json=fixture_response("auth_401.json")
    )
    result = CliRunner().invoke(app, ["dcim", "devices", "list", "--output", "json"])
    assert result.exit_code == 8  # EXIT_CODES[ErrorType.AUTH]
    parsed = json.loads(result.stdout)
    assert parsed["type"] == "auth"
    assert parsed["status_code"] == 401
    assert parsed["endpoint"].endswith("/api/dcim/devices/")


@pytest.mark.parametrize(
    "status_code,expected_type",
    [
        (401, ErrorType.AUTH),
        (403, ErrorType.AUTH),
        (404, ErrorType.NOT_FOUND),
        (409, ErrorType.CONFLICT),
        (429, ErrorType.RATE_LIMITED),
        (400, ErrorType.VALIDATION),
        (503, ErrorType.SERVER),
    ],
)
def test_read_http_status_maps_to_envelope_and_exit_code(
    status_code: int,
    expected_type: ErrorType,
    monkeypatch: pytest.MonkeyPatch,
    httpx2_mock: respx.Router,
) -> None:
    monkeypatch.setattr("nsc.http.client.time.sleep", lambda _s: None)
    _mock_schema(httpx2_mock)
    httpx2_mock.get("https://nb.example/api/dcim/devices/").respond(
        status_code, json={"detail": "x"}
    )
    result = CliRunner().invoke(app, ["dcim", "devices", "list", "--output", "json"])
    assert result.exit_code == EXIT_CODES[expected_type]
    parsed = json.loads(result.stdout)
    assert parsed["type"] == expected_type.value
    assert parsed["endpoint"].endswith("/api/dcim/devices/")
    assert parsed["status_code"] == status_code


def test_read_connect_error_maps_to_transport_envelope(
    monkeypatch: pytest.MonkeyPatch,
    httpx2_mock: respx.Router,
) -> None:
    monkeypatch.setattr("nsc.http.client.time.sleep", lambda _s: None)
    _mock_schema(httpx2_mock)
    httpx2_mock.get("https://nb.example/api/dcim/devices/").mock(
        side_effect=httpx2.ConnectError("nope")
    )
    result = CliRunner().invoke(app, ["dcim", "devices", "list", "--output", "json"])
    assert result.exit_code == EXIT_CODES[ErrorType.TRANSPORT]
    parsed = json.loads(result.stdout)
    assert parsed["type"] == "transport"


def test_piped_stdout_falls_back_to_json(
    fixture_response: Callable[[str], dict[str, Any]],
    httpx2_mock: respx.Router,
) -> None:
    _mock_schema(httpx2_mock)
    httpx2_mock.get("https://nb.example/api/dcim/devices/").respond(
        200, json=fixture_response("dcim_devices_list_p2.json")
    )
    result = CliRunner().invoke(app, ["dcim", "devices", "list"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, list)
