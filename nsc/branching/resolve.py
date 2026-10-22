from __future__ import annotations

from typing import TYPE_CHECKING

from nsc.branching.errors import (
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
    """Look `ref` up by name, then by schema_id."""
    for key in ("name", "schema_id"):
        try:
            body = client.get(BRANCHES_PATH, {key: ref})
        except NetBoxAPIError as exc:
            if exc.status_code == _STATUS_NOT_FOUND:
                raise BranchingNotInstalledError() from exc
            raise
        results = body.get("results") or []
        if results:
            return Branch.model_validate(results[0])
    raise BranchNotFoundError(ref)


def require_ready(branch: Branch) -> Branch:
    if branch.status != READY:
        raise BranchNotReadyError(branch.name, branch.status)
    return branch
