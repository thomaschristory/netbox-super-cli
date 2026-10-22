from __future__ import annotations

import json

import pytest
import respx

from nsc.branching.api import (
    archive_branch,
    create_branch,
    delete_branch,
    list_branches,
    list_changes,
    run_action,
    wait_until_ready,
)
from nsc.branching.errors import BranchConflictError, BranchJobTimeoutError, BranchNotReadyError
from nsc.branching.models import Branch
from nsc.http.client import NetBoxClient
from tests.branching._fixtures import FakeClock, FakeProfile, branch_json, job_json, page

BASE = "https://nb.example/api/plugins/branching"


def _branch(**over: object) -> Branch:
    return Branch.model_validate(branch_json(**over))


def test_list_branches_paginates(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get(f"{BASE}/branches/", params={"offset": "1"}).respond(
        200, json=page(branch_json(id=4, name="b"))
    )
    httpx2_mock.get(f"{BASE}/branches/").respond(
        200, json=page(branch_json(), next_url=f"{BASE}/branches/?offset=1")
    )
    with NetBoxClient(FakeProfile()) as client:
        names = [b.name for b in list_branches(client)]
    assert names == ["my-change", "b"]


def test_create_then_wait_until_ready(httpx2_mock: respx.Router) -> None:
    create = httpx2_mock.post(f"{BASE}/branches/").respond(
        201, json=branch_json(status={"value": "new"})
    )
    httpx2_mock.get(f"{BASE}/branches/3/").mock(
        side_effect=[
            respx.MockResponse(200, json=branch_json(status={"value": "provisioning"})),
            respx.MockResponse(200, json=branch_json()),
        ]
    )
    fake = FakeClock()
    with NetBoxClient(FakeProfile()) as client:
        created = create_branch(client, "my-change", description="d")
        ready = wait_until_ready(client, created, timeout=60, sleep=fake.sleep, clock=fake.clock)
    assert json.loads(create.calls.last.request.content) == {
        "name": "my-change",
        "description": "d",
    }
    assert ready.status == "ready"


def test_wait_until_ready_failed_raises(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get(f"{BASE}/branches/3/").respond(
        200, json=branch_json(status={"value": "failed"})
    )
    fake = FakeClock()
    with NetBoxClient(FakeProfile()) as client, pytest.raises(BranchNotReadyError):
        wait_until_ready(
            client, _branch(status="new"), timeout=60, sleep=fake.sleep, clock=fake.clock
        )


def test_wait_until_ready_times_out(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get(f"{BASE}/branches/3/").respond(
        200, json=branch_json(status={"value": "provisioning"})
    )
    fake = FakeClock()
    with NetBoxClient(FakeProfile()) as client, pytest.raises(BranchJobTimeoutError):
        wait_until_ready(
            client, _branch(status="new"), timeout=5, sleep=fake.sleep, clock=fake.clock
        )


def test_run_action_merge_dry_run_posts_commit_false(httpx2_mock: respx.Router) -> None:
    route = httpx2_mock.post(f"{BASE}/branches/3/merge/").respond(200, json=job_json())
    with NetBoxClient(FakeProfile()) as client:
        job = run_action(client, _branch(), "merge", commit=False)
    assert json.loads(route.calls.last.request.content) == {"commit": False}
    assert job["id"] == 7


def test_run_action_ack_conflicts_flag(httpx2_mock: respx.Router) -> None:
    route = httpx2_mock.post(f"{BASE}/branches/3/sync/").respond(200, json=job_json())
    with NetBoxClient(FakeProfile()) as client:
        run_action(client, _branch(), "sync", commit=True, acknowledge_conflicts=True)
    assert json.loads(route.calls.last.request.content) == {
        "commit": True,
        "acknowledge_conflicts": True,
    }


def test_run_action_409_raises_conflict_error(httpx2_mock: respx.Router) -> None:
    conflicts = [{"id": 6, "object_repr": "switch-01", "conflicts": ["name"]}]
    httpx2_mock.post(f"{BASE}/branches/3/merge/").respond(
        409, json={"detail": "All conflicts must be acknowledged", "conflicts": conflicts}
    )
    with NetBoxClient(FakeProfile()) as client, pytest.raises(BranchConflictError) as info:
        run_action(client, _branch(), "merge", commit=True)
    assert info.value.conflicts == conflicts


def test_archive_and_delete(httpx2_mock: respx.Router) -> None:
    httpx2_mock.post(f"{BASE}/branches/3/archive/").respond(
        200, json=branch_json(status={"value": "archived"})
    )
    delete = httpx2_mock.delete(f"{BASE}/branches/3/").respond(204)
    with NetBoxClient(FakeProfile()) as client:
        assert archive_branch(client, _branch(status="merged")).status == "archived"
        delete_branch(client, _branch())
    assert delete.call_count == 1


def test_list_changes_paginates(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get(f"{BASE}/changes/", params={"branch_id": "3", "offset": "1"}).respond(
        200, json=page({"id": 2})
    )
    route = httpx2_mock.get(f"{BASE}/changes/").respond(
        200, json=page({"id": 1}, next_url=f"{BASE}/changes/?branch_id=3&offset=1")
    )
    with NetBoxClient(FakeProfile()) as client:
        ids = [c["id"] for c in list_changes(client, _branch())]
    assert ids == [1, 2]
    assert route.calls[0].request.url.params["branch_id"] == "3"
