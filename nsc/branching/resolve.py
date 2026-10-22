from __future__ import annotations

from typing import TYPE_CHECKING

from nsc.branching.errors import (
    BranchAmbiguousError,
    BranchingNotInstalledError,
    BranchNotFoundError,
    BranchNotReadyError,
)
from nsc.branching.models import BRANCHES_PATH, READY, Branch
from nsc.http.errors import NetBoxAPIError

if TYPE_CHECKING:
    from nsc.http.client import NetBoxClient

_STATUS_NOT_FOUND = 404


def get_branch(client: NetBoxClient, ref: str) -> Branch:
    """Look `ref` up as a name and as a schema_id; both must agree."""
    by_name = _exact(client, "name", ref)
    by_schema = _exact(client, "schema_id", ref)
    if by_name is not None and by_schema is not None and by_name.id != by_schema.id:
        raise BranchAmbiguousError(ref)
    branch = by_name or by_schema
    if branch is None:
        raise BranchNotFoundError(ref)
    return branch


def _exact(client: NetBoxClient, key: str, ref: str) -> Branch | None:
    try:
        body = client.get(BRANCHES_PATH, {key: ref})
    except NetBoxAPIError as exc:
        if exc.status_code == _STATUS_NOT_FOUND:
            raise BranchingNotInstalledError() from exc
        raise
    matches = [r for r in body.get("results") or [] if r.get(key) == ref]
    return Branch.model_validate(matches[0]) if len(matches) == 1 else None


def require_ready(branch: Branch) -> Branch:
    if branch.status != READY:
        raise BranchNotReadyError(branch.name, branch.status)
    return branch
