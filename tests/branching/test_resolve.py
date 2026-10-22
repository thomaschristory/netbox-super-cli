from __future__ import annotations

from typing import Any

import pytest
import respx

from nsc.branching.errors import (
    BranchingNotInstalledError,
    BranchNotFoundError,
    BranchNotReadyError,
)
from nsc.branching.models import Branch
from nsc.branching.resolve import get_branch, require_ready
from nsc.http.client import NetBoxClient

BRANCHES = "https://nb.example/api/plugins/branching/branches/"


class _FakeProfile:
    url = "https://nb.example"
    token = "tok"
    verify_ssl = True
    timeout = 5.0


def _branch(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": 3,
        "name": "my-change",
        "schema_id": "abcd1234",
        "status": {"value": "ready", "label": "Ready"},
        "owner": {"id": 1, "username": "admin"},
        "description": "",
        "last_sync": None,
    }
    data.update(over)
    return data


def _page(*results: dict[str, Any]) -> dict[str, Any]:
    return {"count": len(results), "next": None, "previous": None, "results": list(results)}


def test_resolve_by_name(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get(BRANCHES, params={"name": "my-change"}).respond(200, json=_page(_branch()))
    with NetBoxClient(_FakeProfile()) as client:
        branch = get_branch(client, "my-change")
    assert branch.schema_id == "abcd1234"
    assert branch.status == "ready"
    assert branch.owner == "admin"


def test_resolve_by_schema_id_fallback(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get(BRANCHES, params={"name": "abcd1234"}).respond(200, json=_page())
    httpx2_mock.get(BRANCHES, params={"schema_id": "abcd1234"}).respond(200, json=_page(_branch()))
    with NetBoxClient(_FakeProfile()) as client:
        branch = get_branch(client, "abcd1234")
    assert branch.name == "my-change"


def test_resolve_not_found_raises(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get(BRANCHES).respond(200, json=_page())
    with NetBoxClient(_FakeProfile()) as client, pytest.raises(BranchNotFoundError) as info:
        get_branch(client, "nope")
    assert "nope" in str(info.value)
    assert "nsc branch list" in str(info.value)


def test_plugin_missing_404_raises_not_installed(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get(BRANCHES).respond(404, json={"detail": "Not found."})
    with NetBoxClient(_FakeProfile()) as client, pytest.raises(BranchingNotInstalledError):
        get_branch(client, "my-change")


def test_require_ready_rejects_merged() -> None:
    merged = Branch.model_validate(_branch(status={"value": "merged", "label": "Merged"}))
    with pytest.raises(BranchNotReadyError) as info:
        require_ready(merged)
    assert "merged" in str(info.value)
    assert "nsc branch use --main" in str(info.value)
    assert info.value.branch == "my-change"


def test_require_ready_passes_ready() -> None:
    ready = Branch.model_validate(_branch())
    assert require_ready(ready) is ready
