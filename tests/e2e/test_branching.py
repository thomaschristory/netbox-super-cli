"""Live NetBox Branching e2e: stage in a branch, review, merge.

Runs against NetBox 4.7 + netboxlabs-netbox-branching (see
tests/e2e/docker-compose.branching.yml). Gated on NSC_E2E_BRANCHING=1.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator

import httpx2
import pytest

from tests.e2e.conftest import CompletedNsc

RunNsc = Callable[..., CompletedNsc]

# Must match tests/e2e/branching/Dockerfile and the e2e-branching job. On these
# versions the plugin reports the conflicting edit, so a clean merge is a regression.
PINNED_NETBOX = "4.7.3"
PINNED_BRANCHING = "1.2.2"


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _tag_names_on_main(netbox_client: httpx2.Client) -> set[str]:
    r = netbox_client.get("/api/extras/tags/", params={"limit": 1000})
    r.raise_for_status()
    return {t["name"] for t in r.json()["results"]}


@pytest.fixture
def branch(run_nsc: RunNsc) -> Iterator[str]:
    name = _name("e2e")
    r = run_nsc("branch", "create", name, "--output", "json", timeout=300)
    assert r.returncode == 0, r.stderr
    assert r.stdout_json()["status"] == "ready"  # type: ignore[index]
    yield name
    run_nsc("branch", "delete", name, "--apply")


@pytest.mark.usefixtures("clean_tags")
def test_branch_create_write_diff_merge(
    run_nsc: RunNsc, netbox_client: httpx2.Client, branch: str
) -> None:
    tag = _name("tag")
    in_branch = {"NSC_BRANCH": branch}
    r = run_nsc(
        "extras",
        "tags",
        "create",
        "--field",
        f"name={tag}",
        "--field",
        f"slug={tag}",
        "--apply",
        "--output",
        "json",
        env=in_branch,
    )
    assert r.returncode == 0, r.stderr
    assert f"⎇ branch: {branch}" in r.stderr

    assert tag not in _tag_names_on_main(netbox_client)
    r = run_nsc("extras", "tags", "list", "--output", "json", env=in_branch)
    assert tag in {t["name"] for t in r.stdout_json()}  # type: ignore[union-attr]

    r = run_nsc("branch", "diff", branch, "--output", "json")
    assert r.returncode == 0, r.stderr
    changes = r.stdout_json()
    assert [(c["object_type"], c["object_repr"]) for c in changes] == [  # type: ignore[union-attr]
        ("extras.tag", tag)
    ]

    r = run_nsc("branch", "merge", branch, "--output", "json", timeout=300)
    assert r.returncode == 0, r.stderr
    assert "dry-run: merge" in r.stderr
    assert tag not in _tag_names_on_main(netbox_client)

    r = run_nsc("branch", "merge", branch, "--apply", "--output", "json", timeout=300)
    assert r.returncode == 0, r.stderr
    assert tag in _tag_names_on_main(netbox_client)

    r = run_nsc("extras", "tags", "list", "--output", "json", env=in_branch)
    assert r.returncode == 12, r.stdout
    envelope = json.loads(r.stdout)
    assert envelope["details"] == {"branch": branch, "status": "merged"}


def test_unknown_branch_not_found(run_nsc: RunNsc) -> None:
    r = run_nsc("extras", "tags", "list", "--output", "json", env={"NSC_BRANCH": _name("nope")})
    assert r.returncode == 9, (r.stdout, r.stderr)
    assert json.loads(r.stdout)["type"] == "not_found"


@pytest.mark.usefixtures("clean_tags")
def test_conflict_on_merge(run_nsc: RunNsc, netbox_client: httpx2.Client, branch: str) -> None:
    tag = _name("tag")
    created = netbox_client.post("/api/extras/tags/", json={"name": tag, "slug": tag})
    created.raise_for_status()
    tag_id = created.json()["id"]

    r = run_nsc("branch", "sync", branch, "--apply", "--output", "json", timeout=300)
    assert r.returncode == 0, r.stderr
    r = run_nsc(
        "extras",
        "tags",
        "update",
        str(tag_id),
        "--field",
        "description=from-branch",
        "--apply",
        "--output",
        "json",
        env={"NSC_BRANCH": branch},
    )
    assert r.returncode == 0, r.stderr
    netbox_client.patch(f"/api/extras/tags/{tag_id}/", json={"description": "from-main"})

    r = run_nsc("branch", "merge", branch, "--output", "json", timeout=300)
    if r.returncode == 0:
        status = netbox_client.get("/api/status/").json()
        versions = (status["netbox-version"], status["plugins"].get("netbox_branching"))
        if versions == (PINNED_NETBOX, PINNED_BRANCHING):
            pytest.fail(f"merge reported no conflict on pinned versions {versions}: {r.stdout}")
        pytest.skip(f"no conflict reported on unpinned versions {versions}; nothing to assert")
    assert r.returncode == 10, (r.stdout, r.stderr)
    assert json.loads(r.stdout)["details"]["conflicts"]

    r = run_nsc(
        "branch",
        "merge",
        branch,
        "--apply",
        "--acknowledge-conflicts",
        "--output",
        "json",
        timeout=300,
    )
    assert r.returncode == 0, r.stderr
    detail = netbox_client.get(f"/api/extras/tags/{tag_id}/").json()
    assert detail["description"] == "from-branch"
