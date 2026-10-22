from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
import respx

from nsc.branching.errors import BranchNotReadyError
from nsc.http.client import NetBoxClient

SITES = "https://nb.example/api/dcim/sites/"
LOOKUP = "https://nb.example/api/plugins/branching/branches/"


class _FakeProfile:
    url = "https://nb.example"
    token = "tok"
    verify_ssl = True
    timeout = 5.0


def _resolver(client: NetBoxClient) -> str:
    client.get("/api/plugins/branching/branches/", {"name": "my-change"})
    return "abcd1234"


def test_client_sends_branch_header_after_lazy_resolve(httpx2_mock: respx.Router) -> None:
    lookup = httpx2_mock.get(LOOKUP).respond(200, json={"results": []})
    sites = httpx2_mock.get(SITES).respond(200, json={"results": []})
    with NetBoxClient(_FakeProfile(), branch_resolver=_resolver) as client:
        client.get("/api/dcim/sites/")
        client.get("/api/dcim/sites/")
    assert "x-netbox-branch" not in lookup.calls.last.request.headers
    assert lookup.call_count == 1
    assert sites.calls.last.request.headers["X-NetBox-Branch"] == "abcd1234"


def test_no_header_without_resolver(httpx2_mock: respx.Router) -> None:
    sites = httpx2_mock.get(SITES).respond(200, json={"results": []})
    with NetBoxClient(_FakeProfile()) as client:
        client.get("/api/dcim/sites/")
    assert "x-netbox-branch" not in sites.calls.last.request.headers


def test_header_sent_on_paginated_followups(httpx2_mock: respx.Router) -> None:
    page2 = httpx2_mock.get(SITES, params={"offset": "1"}).respond(
        200, json={"count": 2, "next": None, "results": [{"id": 2}]}
    )
    httpx2_mock.get(SITES).respond(
        200, json={"count": 2, "next": f"{SITES}?offset=1", "results": [{"id": 1}]}
    )
    with NetBoxClient(_FakeProfile(), branch_resolver=lambda c: "abcd1234") as client:
        ids = [r["id"] for r in client.paginate("/api/dcim/sites/")]
    assert ids == [1, 2]
    assert page2.calls.last.request.headers["X-NetBox-Branch"] == "abcd1234"


@pytest.mark.httpx2(assert_all_called=False)
def test_resolver_failure_is_sticky_and_no_request_hits_main(httpx2_mock: respx.Router) -> None:
    sites = httpx2_mock.get(SITES).respond(200, json={"results": []})
    calls = 0

    def failing(client: NetBoxClient) -> str:
        nonlocal calls
        calls += 1
        raise BranchNotReadyError("my-change", "merged")

    with NetBoxClient(_FakeProfile(), branch_resolver=failing) as client:
        with pytest.raises(BranchNotReadyError):
            client.get("/api/dcim/sites/")
        with pytest.raises(BranchNotReadyError):
            client.get("/api/dcim/sites/")
    assert sites.call_count == 0
    assert calls == 1


def test_audit_entry_records_branch_header(
    httpx2_mock: respx.Router, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NSC_HOME", str(tmp_path))
    httpx2_mock.post(SITES).respond(201, json={"id": 1})
    with NetBoxClient(_FakeProfile(), branch_resolver=lambda c: "abcd1234") as client:
        client.post("/api/dcim/sites/", json={"name": "x"})
    line = (tmp_path / "logs" / "audit.jsonl").read_text().splitlines()[-1]
    assert json.loads(line)["request"]["headers"]["X-Netbox-Branch"] == "abcd1234"


def test_concurrent_requests_wait_for_branch_resolution(httpx2_mock: respx.Router) -> None:
    sites = httpx2_mock.get(SITES).respond(200, json={"results": []})
    started = threading.Event()
    release = threading.Event()

    def slow(client: NetBoxClient) -> str:
        started.set()
        release.wait(5)
        return "abcd1234"

    with NetBoxClient(_FakeProfile(), branch_resolver=slow) as client:
        first = threading.Thread(target=client.get, args=("/api/dcim/sites/",))
        first.start()
        started.wait(5)
        second = threading.Thread(target=client.get, args=("/api/dcim/sites/",))
        second.start()
        second.join(0.2)
        assert sites.call_count == 0
        release.set()
        first.join(5)
        second.join(5)
    assert sites.call_count == 2
    assert all(c.request.headers["X-NetBox-Branch"] == "abcd1234" for c in sites.calls)
