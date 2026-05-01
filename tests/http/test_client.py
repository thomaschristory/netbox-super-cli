from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from nsc.http.client import NetBoxClient
from nsc.http.errors import NetBoxAPIError, NetBoxClientError


class _FakeProfile:
    def __init__(self, **overrides: Any) -> None:
        self.url: str = overrides.get("url", "https://nb.example")
        self.token: str | None = overrides.get("token", "tok")
        self.verify_ssl: bool = overrides.get("verify_ssl", True)
        self.timeout: float = overrides.get("timeout", 5.0)


@respx.mock
def test_get_returns_parsed_json_with_auth_header() -> None:
    respx.get("https://nb.example/api/dcim/devices/1/").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "x"})
    )
    with NetBoxClient(_FakeProfile()) as client:
        body = client.get("/api/dcim/devices/1/")
    assert body == {"id": 1, "name": "x"}
    sent = respx.calls.last.request
    assert sent.headers["Authorization"] == "Token tok"
    assert sent.headers["Accept"] == "application/json"


@respx.mock
def test_get_passes_query_params() -> None:
    route = respx.get("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    with NetBoxClient(_FakeProfile()) as client:
        client.get("/api/dcim/devices/", {"site_id": 42, "status": "active"})
    qp = dict(route.calls.last.request.url.params)
    assert qp == {"site_id": "42", "status": "active"}


@respx.mock
def test_paginate_follows_next_url() -> None:
    # Register the more-specific route first; respx resolves by first match.
    respx.get("https://nb.example/api/dcim/devices/", params={"cursor": "p2"}).mock(
        return_value=httpx.Response(
            200,
            json={"count": 3, "next": None, "previous": None, "results": [{"id": 3}]},
        )
    )
    respx.get("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 3,
                "next": "https://nb.example/api/dcim/devices/?cursor=p2",
                "previous": None,
                "results": [{"id": 1}, {"id": 2}],
            },
        )
    )
    with NetBoxClient(_FakeProfile()) as client:
        records = list(client.paginate("/api/dcim/devices/"))
    assert [r["id"] for r in records] == [1, 2, 3]


@respx.mock
def test_paginate_stops_when_limit_reached() -> None:
    respx.get("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(
            200,
            json={
                "next": "https://nb.example/api/dcim/devices/?cursor=p2",
                "results": [{"id": 1}, {"id": 2}, {"id": 3}],
            },
        )
    )
    with NetBoxClient(_FakeProfile()) as client:
        records = list(client.paginate("/api/dcim/devices/", limit=2))
    assert [r["id"] for r in records] == [1, 2]
    assert all("cursor" not in str(c.request.url) for c in respx.calls)


@respx.mock
def test_get_raises_netbox_api_error_on_4xx() -> None:
    respx.get("https://nb.example/api/dcim/devices/9999/").mock(
        return_value=httpx.Response(404, json={"detail": "Not found."})
    )
    with NetBoxClient(_FakeProfile()) as client, pytest.raises(NetBoxAPIError) as excinfo:
        client.get("/api/dcim/devices/9999/")
    assert excinfo.value.status_code == 404
    assert "Not found" in excinfo.value.body_snippet


@respx.mock
def test_get_raises_netbox_client_error_on_transport_failure() -> None:
    respx.get("https://nb.example/api/dcim/devices/").mock(side_effect=httpx.ConnectError("nope"))
    with NetBoxClient(_FakeProfile()) as client, pytest.raises(NetBoxClientError):
        client.get("/api/dcim/devices/")


@respx.mock
def test_debug_writes_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    respx.get("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    with NetBoxClient(_FakeProfile(), debug=True) as client:
        client.get("/api/dcim/devices/")
    err = capsys.readouterr().err
    assert ">>> GET" in err
    assert "<<< 200" in err
    assert "Token tok" not in err
    assert "<redacted>" in err
