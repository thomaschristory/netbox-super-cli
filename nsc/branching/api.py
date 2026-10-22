from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, Literal

from nsc.branching.errors import (
    BranchConflictError,
    BranchJobTimeoutError,
    BranchNotReadyError,
)
from nsc.branching.jobs import Clock, Sleep, backoff_delays
from nsc.branching.models import BRANCHES_PATH, CHANGES_PATH, READY, Branch
from nsc.http.errors import NetBoxAPIError

if TYPE_CHECKING:
    from nsc.http.client import NetBoxClient

Action = Literal["sync", "merge", "revert"]

_STATUS_CONFLICT = 409
_FAILED = "failed"


def list_branches(client: NetBoxClient) -> list[Branch]:
    return [Branch.model_validate(r) for r in client.paginate(BRANCHES_PATH)]


def fetch_branch(client: NetBoxClient, branch: Branch) -> Branch:
    return Branch.model_validate(client.get(f"{BRANCHES_PATH}{branch.id}/"))


def create_branch(client: NetBoxClient, name: str, description: str = "") -> Branch:
    body = client.post(BRANCHES_PATH, json={"name": name, "description": description})
    return Branch.model_validate(body)


def wait_until_ready(
    client: NetBoxClient,
    branch: Branch,
    *,
    timeout: float,
    sleep: Sleep = time.sleep,
    clock: Clock = time.monotonic,
) -> Branch:
    deadline = clock() + timeout
    delays = backoff_delays()
    while True:
        current = fetch_branch(client, branch)
        if current.status == READY:
            return current
        if current.status == _FAILED:
            raise BranchNotReadyError(current.name, current.status)
        if clock() >= deadline:
            raise BranchJobTimeoutError(current.name, None)
        sleep(next(delays))


def run_action(
    client: NetBoxClient,
    branch: Branch,
    action: Action,
    *,
    commit: bool,
    acknowledge_conflicts: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"commit": commit}
    if acknowledge_conflicts:
        payload["acknowledge_conflicts"] = True
    try:
        return client.post(f"{BRANCHES_PATH}{branch.id}/{action}/", json=payload)
    except NetBoxAPIError as exc:
        conflicts = _conflicts(exc)
        if conflicts is not None:
            raise BranchConflictError(branch.name, conflicts) from exc
        raise


def _conflicts(exc: NetBoxAPIError) -> list[dict[str, Any]] | None:
    if exc.status_code != _STATUS_CONFLICT:
        return None
    try:
        body = json.loads(exc.body_snippet)
    except ValueError:
        return []
    conflicts = body.get("conflicts") if isinstance(body, dict) else None
    return conflicts if isinstance(conflicts, list) else []


def archive_branch(client: NetBoxClient, branch: Branch) -> Branch:
    return Branch.model_validate(client.post(f"{BRANCHES_PATH}{branch.id}/archive/"))


def delete_branch(client: NetBoxClient, branch: Branch) -> None:
    client.delete(f"{BRANCHES_PATH}{branch.id}/")


def list_changes(client: NetBoxClient, branch: Branch) -> list[dict[str, Any]]:
    return list(client.paginate(CHANGES_PATH, {"branch_id": branch.id}))
