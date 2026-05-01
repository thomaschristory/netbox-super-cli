from __future__ import annotations

import json
from pathlib import Path
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


def test_get_raises_netbox_client_error_on_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("nsc.http.client.time.sleep", lambda _s: None)
    with respx.mock(base_url="https://nb.example") as router:
        router.get("/api/dcim/devices/").mock(side_effect=httpx.ConnectError("nope"))
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


# ---------------------------------------------------------------------------
# Phase 3a: retry loop + audit log integration tests
# ---------------------------------------------------------------------------


def test_get_5xx_retried_three_times_then_raises_apierror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("nsc.http.client.time.sleep", lambda _s: None)
    with respx.mock(base_url="https://nb.example") as router:
        route = router.get("/api/dcim/devices/").mock(
            return_value=httpx.Response(503, json={"detail": "down"})
        )
        with NetBoxClient(_FakeProfile()) as client, pytest.raises(NetBoxAPIError) as ei:
            client.get("/api/dcim/devices/")
        assert route.call_count == 3
        assert ei.value.status_code == 503


def test_get_connect_error_retried_then_raises_clienterror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("nsc.http.client.time.sleep", lambda _s: None)
    with respx.mock(base_url="https://nb.example") as router:
        route = router.get("/api/dcim/devices/").mock(side_effect=httpx.ConnectError("nope"))
        with NetBoxClient(_FakeProfile()) as client, pytest.raises(NetBoxClientError):
            client.get("/api/dcim/devices/")
        assert route.call_count == 3


def test_get_4xx_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nsc.http.client.time.sleep", lambda _s: None)
    with respx.mock(base_url="https://nb.example") as router:
        route = router.get("/api/dcim/devices/").mock(return_value=httpx.Response(404))
        with NetBoxClient(_FakeProfile()) as client, pytest.raises(NetBoxAPIError):
            client.get("/api/dcim/devices/")
        assert route.call_count == 1


def test_get_writes_last_request_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NSC_HOME", str(tmp_path))
    with respx.mock(base_url="https://nb.example") as router:
        router.get("/api/dcim/devices/").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        with NetBoxClient(_FakeProfile()) as client:
            client.get("/api/dcim/devices/")
    log = tmp_path / "logs" / "last-request.json"
    assert log.exists()
    parsed = json.loads(log.read_text())
    assert parsed["method"] == "GET"
    assert parsed["request"]["headers"]["Authorization"] == "<redacted>"
    assert parsed["response"]["status_code"] == 200


def test_paginate_writes_one_log_per_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NSC_HOME", str(tmp_path))
    with respx.mock(base_url="https://nb.example") as router:
        # Register the more-specific route first; respx resolves by first match.
        router.get("/api/dcim/devices/", params={"page": "2"}).mock(
            return_value=httpx.Response(
                200,
                json={"results": [{"id": 2}], "next": None},
            )
        )
        router.get("/api/dcim/devices/").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [{"id": 1}],
                    "next": "https://nb.example/api/dcim/devices/?page=2",
                },
            )
        )
        with NetBoxClient(_FakeProfile()) as client:
            ids = [r["id"] for r in client.paginate("/api/dcim/devices/")]
        assert ids == [1, 2]
    parsed = json.loads((tmp_path / "logs" / "last-request.json").read_text())
    assert parsed["url"].endswith("page=2")


def test_debug_mode_appends_to_audit_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NSC_HOME", str(tmp_path))
    with respx.mock(base_url="https://nb.example") as router:
        router.get("/api/dcim/devices/").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        with NetBoxClient(_FakeProfile(), debug=True) as client:
            client.get("/api/dcim/devices/")
    audit = tmp_path / "logs" / "audit.jsonl"
    assert audit.exists()
    assert len(audit.read_text().splitlines()) == 1


# ---------------------------------------------------------------------------
# Phase 3b: write methods + audit hooks
# ---------------------------------------------------------------------------


@respx.mock
def test_post_sends_json_body_and_returns_response() -> None:
    route = respx.post("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(201, json={"id": 247, "name": "rack-01"})
    )
    client = NetBoxClient(_FakeProfile())
    body = client.post(
        "/api/dcim/devices/",
        json={"name": "rack-01"},
        operation_id="dcim_devices_create",
    )
    assert body == {"id": 247, "name": "rack-01"}
    assert route.called
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"name": "rack-01"}


@respx.mock
def test_post_5xx_does_not_retry() -> None:
    route = respx.post("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(503, json={"detail": "down"})
    )
    client = NetBoxClient(_FakeProfile())
    with pytest.raises(NetBoxAPIError):
        client.post(
            "/api/dcim/devices/",
            json={"name": "x"},
            operation_id="dcim_devices_create",
        )
    assert route.call_count == 1


def test_post_connect_error_retries_then_surfaces_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("nsc.http.client.time.sleep", lambda _s: None)
    with respx.mock(base_url="https://nb.example") as router:
        route = router.post("/api/dcim/devices/").mock(side_effect=httpx.ConnectError("nope"))
        client = NetBoxClient(_FakeProfile())
        with pytest.raises(NetBoxClientError):
            client.post(
                "/api/dcim/devices/",
                json={"name": "x"},
                operation_id="dcim_devices_create",
            )
        assert route.call_count == 3


@respx.mock
def test_patch_sends_partial_body() -> None:
    route = respx.patch("https://nb.example/api/dcim/devices/42/").mock(
        return_value=httpx.Response(200, json={"id": 42, "status": "decommissioned"})
    )
    client = NetBoxClient(_FakeProfile())
    body = client.patch(
        "/api/dcim/devices/42/",
        json={"status": "decommissioned"},
        operation_id="dcim_devices_partial_update",
    )
    assert body == {"id": 42, "status": "decommissioned"}
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"status": "decommissioned"}


@respx.mock
def test_put_sends_full_body() -> None:
    route = respx.put("https://nb.example/api/dcim/devices/42/").mock(
        return_value=httpx.Response(200, json={"id": 42})
    )
    client = NetBoxClient(_FakeProfile())
    client.put(
        "/api/dcim/devices/42/",
        json={"name": "x", "status": "active"},
        operation_id="dcim_devices_update",
    )
    assert route.called


@respx.mock
def test_delete_sends_no_body_returns_empty_dict() -> None:
    route = respx.delete("https://nb.example/api/dcim/devices/42/").mock(
        return_value=httpx.Response(204)
    )
    client = NetBoxClient(_FakeProfile())
    result = client.delete("/api/dcim/devices/42/", operation_id="dcim_devices_destroy")
    assert result == {}
    assert route.called


@respx.mock
def test_delete_404_raises_apierror_with_status() -> None:
    respx.delete("https://nb.example/api/dcim/devices/42/").mock(
        return_value=httpx.Response(404, json={"detail": "Not found."})
    )
    client = NetBoxClient(_FakeProfile())
    with pytest.raises(NetBoxAPIError) as exc_info:
        client.delete("/api/dcim/devices/42/", operation_id="dcim_devices_destroy")
    assert exc_info.value.status_code == 404


@respx.mock
def test_audit_jsonl_appended_for_every_write_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NSC_HOME", str(tmp_path))
    respx.post("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(201, json={"id": 1})
    )
    client = NetBoxClient(_FakeProfile())
    client.post(
        "/api/dcim/devices/",
        json={"name": "rack-01"},
        operation_id="dcim_devices_create",
    )
    log = (tmp_path / "logs" / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(log) == 1
    entry = json.loads(log[0])
    assert entry["method"] == "POST"
    assert entry["operation_id"] == "dcim_devices_create"
    assert entry["request"]["body"] == {"name": "rack-01"}
    assert entry["response"]["status_code"] == 201
    assert entry["request"]["headers"]["Authorization"] == "<redacted>"
