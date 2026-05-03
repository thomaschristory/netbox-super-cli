"""Integration tests for `nsc ls`, `nsc rm`, `nsc get`, and `nsc search` aliases."""

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


# ---------------------------------------------------------------------------
# nsc rm tests
# ---------------------------------------------------------------------------


@respx.mock
def test_rm_by_id_numeric_dry_run_does_not_call_delete() -> None:
    _mock_schema(respx.mock)
    delete_route = respx.delete("https://nb.example/api/dcim/devices/42/").mock(
        return_value=httpx.Response(204)
    )
    result = CliRunner().invoke(app, ["rm", "devices", "42", "--output", "json"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert delete_route.call_count == 0  # dry-run; no wire delete


@respx.mock
def test_rm_by_id_numeric_apply_calls_delete() -> None:
    _mock_schema(respx.mock)
    delete_route = respx.delete("https://nb.example/api/dcim/devices/42/").mock(
        return_value=httpx.Response(204)
    )
    result = CliRunner().invoke(app, ["rm", "devices", "42", "--apply", "--output", "json"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert delete_route.call_count == 1


@respx.mock
def test_rm_by_name_dereferences_via_list_filter() -> None:
    _mock_schema(respx.mock)
    list_route = respx.get("https://nb.example/api/dcim/devices/", params={"name": "alpha"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "next": None,
                "previous": None,
                "results": [{"id": 99, "name": "alpha"}],
            },
        )
    )
    delete_route = respx.delete("https://nb.example/api/dcim/devices/99/").mock(
        return_value=httpx.Response(204)
    )
    result = CliRunner().invoke(app, ["rm", "devices", "alpha", "--apply", "--output", "json"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert list_route.called
    assert delete_route.call_count == 1


@respx.mock
def test_rm_by_name_zero_matches_emits_unknown_alias() -> None:
    _mock_schema(respx.mock)
    respx.get("https://nb.example/api/dcim/devices/", params={"name": "ghost"}).mock(
        return_value=httpx.Response(
            200, json={"count": 0, "next": None, "previous": None, "results": []}
        )
    )
    result = CliRunner().invoke(app, ["rm", "devices", "ghost", "--apply", "--output", "json"])
    assert result.exit_code == 14, (result.exit_code, result.stdout)
    payload = json.loads(result.stdout)
    assert payload["details"]["reason"] == "name_not_found"


@respx.mock
def test_rm_by_name_multiple_matches_emits_ambiguous_alias() -> None:
    _mock_schema(respx.mock)
    respx.get("https://nb.example/api/dcim/devices/", params={"name": "dup"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "next": None,
                "previous": None,
                "results": [{"id": 1, "name": "dup"}, {"id": 2, "name": "dup"}],
            },
        )
    )
    result = CliRunner().invoke(app, ["rm", "devices", "dup", "--apply", "--output", "json"])
    assert result.exit_code == 13, (result.exit_code, result.stdout)
    payload = json.loads(result.stdout)
    assert payload["type"] == "ambiguous_alias"
    assert payload["details"]["reason"] == "name_matched_multiple"
    assert payload["details"]["matched_ids"] == [1, 2]


# ---------------------------------------------------------------------------
# nsc get tests
# ---------------------------------------------------------------------------


@respx.mock
def test_get_by_id_numeric_calls_retrieve() -> None:
    _mock_schema(respx.mock)
    respx.get("https://nb.example/api/dcim/devices/42/").mock(
        return_value=httpx.Response(200, json={"id": 42, "name": "alpha"})
    )
    result = CliRunner().invoke(app, ["get", "devices", "42", "--output", "json"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert json.loads(result.stdout) == {"id": 42, "name": "alpha"}


@respx.mock
def test_get_by_name_dereferences_then_retrieves() -> None:
    _mock_schema(respx.mock)
    respx.get("https://nb.example/api/dcim/devices/", params={"name": "alpha"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "next": None,
                "previous": None,
                "results": [{"id": 7, "name": "alpha"}],
            },
        )
    )
    retrieve_route = respx.get("https://nb.example/api/dcim/devices/7/").mock(
        return_value=httpx.Response(200, json={"id": 7, "name": "alpha"})
    )
    result = CliRunner().invoke(app, ["get", "devices", "alpha", "--output", "json"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert retrieve_route.called
    assert json.loads(result.stdout) == {"id": 7, "name": "alpha"}


@respx.mock
def test_get_by_name_zero_matches_emits_unknown_alias() -> None:
    _mock_schema(respx.mock)
    respx.get("https://nb.example/api/dcim/devices/", params={"name": "ghost"}).mock(
        return_value=httpx.Response(
            200, json={"count": 0, "next": None, "previous": None, "results": []}
        )
    )
    result = CliRunner().invoke(app, ["get", "devices", "ghost", "--output", "json"])
    assert result.exit_code == 14, (result.exit_code, result.stdout)
    payload = json.loads(result.stdout)
    assert payload["details"]["reason"] == "name_not_found"


# ---------------------------------------------------------------------------
# nsc search tests
# ---------------------------------------------------------------------------


def _mock_schema_with_search(respx_mock: Any) -> None:
    """Same as _mock_schema but injects a /api/search/ GET op into the bundled schema."""
    bundled = next(Path("nsc/schemas/bundled").glob("*.json*"))
    raw = (
        gzip.decompress(bundled.read_bytes())
        if bundled.name.endswith(".gz")
        else bundled.read_bytes()
    )
    doc = json.loads(raw)
    doc.setdefault("paths", {})["/api/search/"] = {
        "get": {
            "operationId": "core_search",
            "tags": ["core"],
            "parameters": [
                {"name": "q", "in": "query", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {"200": {"description": "ok"}},
        },
    }
    body = json.dumps(doc).encode("utf-8")
    respx_mock.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, content=body, headers={"content-type": "application/json"})
    )


@respx.mock
def test_search_unavailable_in_schema_emits_unknown_alias() -> None:
    """When /api/search/ is missing, exit 14 with the search-specific reason."""
    _mock_schema(respx.mock)
    result = CliRunner().invoke(app, ["search", "anything", "--output", "json"])
    assert result.exit_code == 14, (result.exit_code, result.stdout)
    payload = json.loads(result.stdout)
    assert payload["type"] == "unknown_alias"
    assert payload["details"]["reason"] == "search_endpoint_unavailable"


@respx.mock
def test_search_with_query_calls_endpoint() -> None:
    _mock_schema_with_search(respx.mock)
    route = respx.get("https://nb.example/api/search/", params={"q": "switch01"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "next": None,
                "previous": None,
                "results": [{"object_type": "device"}],
            },
        )
    )
    result = CliRunner().invoke(app, ["search", "switch01", "--output", "json"])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert route.called
