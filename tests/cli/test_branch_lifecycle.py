"""`nsc branch sync|merge|revert|archive|delete` — dry-run by default."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx

from tests.branching._fixtures import branch_json, job_json
from tests.cli.test_branch_commands import (
    BRANCHES,
    NB,
    _invoke,
    _mock_lookup,
    _mock_schema,
)

JOB = f"{NB}/api/core/jobs/7/"


@pytest.fixture(autouse=True)
def _home(monkeypatch: pytest.MonkeyPatch, fixture_profile_yaml: Path) -> Path:
    monkeypatch.setenv("NSC_HOME", str(fixture_profile_yaml))
    for var in ("NSC_BRANCH", "NSC_URL", "NSC_TOKEN", "NSC_PROFILE", "NSC_OUTPUT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("nsc.cli.branch_commands.time.sleep", lambda s: None)
    return fixture_profile_yaml


def test_merge_default_is_dry_run_commit_false(httpx2_mock: respx.Router) -> None:
    _mock_schema(httpx2_mock)
    _mock_lookup(httpx2_mock)
    merge = httpx2_mock.post(f"{BRANCHES}3/merge/").respond(200, json=job_json())
    httpx2_mock.get(JOB).respond(200, json=job_json("completed"))
    result = _invoke("branch", "merge", "my-change", "--output", "json")
    assert result.exit_code == 0, result.output
    assert json.loads(merge.calls.last.request.content) == {"commit": False}
    assert "dry-run: merge my-change (pass --apply to commit)" in result.stderr
    assert json.loads(result.stdout)["status"]["value"] == "completed"


def test_merge_apply_commits_and_waits(httpx2_mock: respx.Router) -> None:
    _mock_schema(httpx2_mock)
    _mock_lookup(httpx2_mock)
    merge = httpx2_mock.post(f"{BRANCHES}3/merge/").respond(200, json=job_json())
    httpx2_mock.get(JOB).mock(
        side_effect=[
            respx.MockResponse(200, json=job_json("running")),
            respx.MockResponse(200, json=job_json("completed")),
        ]
    )
    result = _invoke("branch", "merge", "my-change", "--apply", "--output", "json")
    assert result.exit_code == 0, result.output
    assert json.loads(merge.calls.last.request.content) == {"commit": True}
    assert "applied: merge my-change" in result.stderr


def test_merge_conflict_envelope(httpx2_mock: respx.Router) -> None:
    _mock_schema(httpx2_mock)
    _mock_lookup(httpx2_mock)
    conflicts = [{"id": 6, "object_repr": "switch-01", "conflicts": ["name"]}]
    httpx2_mock.post(f"{BRANCHES}3/merge/").respond(
        409, json={"detail": "All conflicts must be acknowledged", "conflicts": conflicts}
    )
    result = _invoke("branch", "merge", "my-change", "--output", "json")
    assert result.exit_code == 10, result.output
    env = json.loads(result.stdout)
    assert env["type"] == "conflict"
    assert env["details"]["conflicts"][0]["conflicts"] == ["name"]


def test_merge_ack_conflicts_resubmits(httpx2_mock: respx.Router) -> None:
    _mock_schema(httpx2_mock)
    _mock_lookup(httpx2_mock)
    merge = httpx2_mock.post(f"{BRANCHES}3/merge/").respond(200, json=job_json())
    httpx2_mock.get(JOB).respond(200, json=job_json("completed"))
    result = _invoke(
        "branch", "merge", "my-change", "--apply", "--acknowledge-conflicts", "--output", "json"
    )
    assert result.exit_code == 0, result.output
    assert json.loads(merge.calls.last.request.content) == {
        "commit": True,
        "acknowledge_conflicts": True,
    }


def test_merge_job_errored_is_validation_exit_4(httpx2_mock: respx.Router) -> None:
    _mock_schema(httpx2_mock)
    _mock_lookup(httpx2_mock)
    httpx2_mock.post(f"{BRANCHES}3/merge/").respond(200, json=job_json())
    httpx2_mock.get(JOB).respond(
        200, json=job_json("errored", error="Merging this branch is not permitted.")
    )
    result = _invoke("branch", "merge", "my-change", "--apply", "--output", "json")
    assert result.exit_code == 4, result.output
    env = json.loads(result.stdout)
    assert env["details"]["job_error"] == "Merging this branch is not permitted."


@pytest.mark.httpx2(assert_all_called=False)
def test_sync_no_wait_returns_job(httpx2_mock: respx.Router) -> None:
    _mock_schema(httpx2_mock)
    _mock_lookup(httpx2_mock)
    httpx2_mock.post(f"{BRANCHES}3/sync/").respond(200, json=job_json())
    poll = httpx2_mock.get(JOB).respond(200, json=job_json("completed"))
    result = _invoke("branch", "sync", "my-change", "--apply", "--no-wait", "--output", "json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"]["value"] == "pending"
    assert not poll.called


def test_lifecycle_defaults_to_active_branch(httpx2_mock: respx.Router) -> None:
    _mock_schema(httpx2_mock)
    _mock_lookup(httpx2_mock)
    revert = httpx2_mock.post(f"{BRANCHES}3/revert/").respond(200, json=job_json())
    httpx2_mock.get(JOB).respond(200, json=job_json("completed"))
    result = _invoke("--branch", "my-change", "branch", "revert", "--output", "json")
    assert result.exit_code == 0, result.output
    assert json.loads(revert.calls.last.request.content) == {"commit": False}


def test_job_log_entries_rendered_in_table(httpx2_mock: respx.Router) -> None:
    _mock_schema(httpx2_mock)
    _mock_lookup(httpx2_mock)
    httpx2_mock.post(f"{BRANCHES}3/merge/").respond(200, json=job_json())
    httpx2_mock.get(JOB).respond(
        200,
        json=job_json(
            "completed",
            log_entries=[{"level": "info", "message": "Merged 3 changes"}],
        ),
    )
    result = _invoke("branch", "merge", "my-change", "--output", "table")
    assert result.exit_code == 0, result.output
    assert "Merged 3 changes" in result.stderr


@pytest.mark.httpx2(assert_all_called=False)
def test_archive_preview_sends_no_post(httpx2_mock: respx.Router) -> None:
    _mock_schema(httpx2_mock)
    _mock_lookup(httpx2_mock, status={"value": "merged"})
    archive = httpx2_mock.post(f"{BRANCHES}3/archive/").respond(200, json=branch_json())
    result = _invoke("branch", "archive", "my-change")
    assert result.exit_code == 0, result.output
    assert "would archive branch my-change (status merged); pass --apply" in result.stderr
    assert not archive.called


def test_archive_apply(httpx2_mock: respx.Router) -> None:
    _mock_schema(httpx2_mock)
    _mock_lookup(httpx2_mock, status={"value": "merged"})
    httpx2_mock.post(f"{BRANCHES}3/archive/").respond(
        200, json=branch_json(status={"value": "archived"})
    )
    result = _invoke("branch", "archive", "my-change", "--apply", "--output", "json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"] == "archived"


@pytest.mark.httpx2(assert_all_called=False)
def test_delete_requires_apply(httpx2_mock: respx.Router) -> None:
    _mock_schema(httpx2_mock)
    _mock_lookup(httpx2_mock)
    delete = httpx2_mock.delete(f"{BRANCHES}3/").respond(204)
    preview = _invoke("branch", "delete", "my-change")
    assert preview.exit_code == 0, preview.output
    assert "would delete branch my-change (status ready); pass --apply" in preview.stderr
    assert not delete.called
    applied = _invoke("branch", "delete", "my-change", "--apply")
    assert applied.exit_code == 0, applied.output
    assert delete.called


def test_delete_requires_explicit_name(httpx2_mock: respx.Router) -> None:
    _mock_schema(httpx2_mock)
    result = _invoke("--branch", "my-change", "branch", "delete", "--apply")
    assert result.exit_code == 2
