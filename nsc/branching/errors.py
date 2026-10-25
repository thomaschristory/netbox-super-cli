from __future__ import annotations

from typing import Any

_ESCAPE_HINT = "run `nsc branch use --main` or pass `--branch main` to work on main"


class BranchError(Exception):
    """Base for branch failures; `branch` names the branch involved, if any."""

    def __init__(self, message: str, *, branch: str | None = None) -> None:
        super().__init__(message)
        self.branch = branch


class BranchingNotInstalledError(BranchError):
    def __init__(self) -> None:
        super().__init__(
            "the NetBox Branching plugin is not installed on this server "
            "(/api/plugins/branching/ returned 404)"
        )


class BranchNotFoundError(BranchError):
    def __init__(self, ref: str) -> None:
        super().__init__(
            f"branch {ref!r} not found (by name or schema_id); "
            f"see `nsc branch list`, or {_ESCAPE_HINT}",
            branch=ref,
        )


class BranchAmbiguousError(BranchError):
    def __init__(self, ref: str) -> None:
        super().__init__(
            f"{ref!r} is the name of one branch and the schema_id of another; "
            "pass the other branch's name instead",
            branch=ref,
        )


class BranchNotReadyError(BranchError):
    def __init__(self, name: str, status: str) -> None:
        super().__init__(
            f"branch {name!r} is {status}, not ready; {_ESCAPE_HINT}",
            branch=name,
        )
        self.status = status


class BranchUnusableError(BranchError):
    """The server refused a request because the active branch went away mid-session.

    `status` is the branch status when the server names it, else None.
    """

    def __init__(self, name: str, *, status: str | None, missing: bool = False) -> None:
        state = "deleted or not found" if missing else f"status: {status or 'not ready'}"
        super().__init__(
            f"branch {name!r} is no longer usable ({state}); {_ESCAPE_HINT}",
            branch=name,
        )
        self.status = status
        self.missing = missing


class BranchConflictError(BranchError):
    def __init__(self, name: str, conflicts: list[dict[str, Any]]) -> None:
        what = (
            f"{len(conflicts)} unacknowledged conflict(s)"
            if conflicts
            else "unacknowledged conflicts (details unavailable)"
        )
        super().__init__(
            f"branch {name!r} has {what}; review them and re-run with --acknowledge-conflicts",
            branch=name,
        )
        self.conflicts = conflicts


class BranchJobFailedError(BranchError):
    def __init__(self, name: str, job: dict[str, Any]) -> None:
        self.job = job
        self.job_id: int | None = job.get("id")
        self.job_error: str | None = job.get("error") or None
        detail = f": {self.job_error}" if self.job_error else ""
        super().__init__(f"job {self.job_id} for branch {name!r} failed{detail}", branch=name)


class BranchJobTimeoutError(BranchError):
    def __init__(self, name: str, job_id: int | None) -> None:
        what = f"job {job_id}" if job_id is not None else "branch provisioning"
        super().__init__(
            f"timed out waiting for {what} on branch {name!r}; "
            "it may still finish server-side — check `nsc branch show`",
            branch=name,
        )
        self.job_id = job_id
