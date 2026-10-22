from __future__ import annotations

import pytest
import respx

from nsc.branching.errors import BranchJobFailedError, BranchJobTimeoutError
from nsc.branching.jobs import wait_for_job
from nsc.branching.models import Branch
from nsc.http.client import NetBoxClient
from tests.branching._fixtures import FakeClock, FakeProfile, branch_json, job_json

JOB = "https://nb.example/api/core/jobs/7/"
BRANCH = Branch.model_validate(branch_json())


def test_wait_for_job_backoff_and_completed(httpx2_mock: respx.Router) -> None:
    pending = [respx.MockResponse(200, json=job_json("running")) for _ in range(6)]
    httpx2_mock.get(JOB).mock(
        side_effect=[*pending, respx.MockResponse(200, json=job_json("completed"))]
    )
    fake = FakeClock()
    with NetBoxClient(FakeProfile()) as client:
        job = wait_for_job(
            client, job_json(), branch=BRANCH, timeout=600, sleep=fake.sleep, clock=fake.clock
        )
    assert job["status"]["value"] == "completed"
    assert fake.sleeps == [1, 2, 4, 8, 10, 10]


def test_wait_for_job_returns_immediately_when_already_done(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get(JOB).respond(200, json=job_json("completed"))
    fake = FakeClock()
    with NetBoxClient(FakeProfile()) as client:
        job = wait_for_job(
            client, job_json(), branch=BRANCH, timeout=600, sleep=fake.sleep, clock=fake.clock
        )
    assert job["status"]["value"] == "completed"


def test_wait_for_job_errored_raises(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get(JOB).respond(
        200, json=job_json("errored", error="Merging this branch is not permitted.")
    )
    fake = FakeClock()
    with NetBoxClient(FakeProfile()) as client, pytest.raises(BranchJobFailedError) as info:
        wait_for_job(
            client, job_json(), branch=BRANCH, timeout=600, sleep=fake.sleep, clock=fake.clock
        )
    assert info.value.job_error == "Merging this branch is not permitted."


def test_wait_for_job_timeout(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get(JOB).respond(200, json=job_json("running"))
    fake = FakeClock()
    with NetBoxClient(FakeProfile()) as client, pytest.raises(BranchJobTimeoutError) as info:
        wait_for_job(
            client, job_json(), branch=BRANCH, timeout=20, sleep=fake.sleep, clock=fake.clock
        )
    assert info.value.job_id == 7


def test_wait_for_job_uses_job_id_not_url(httpx2_mock: respx.Router) -> None:
    route = httpx2_mock.get("https://h.example/netbox/api/core/jobs/7/").respond(
        200, json=job_json("completed")
    )
    fake = FakeClock()
    job = job_json(url="https://h.example/netbox/api/core/jobs/7/")
    with NetBoxClient(FakeProfile("https://h.example/netbox")) as client:
        wait_for_job(client, job, branch=BRANCH, timeout=60, sleep=fake.sleep, clock=fake.clock)
    assert route.call_count == 1
