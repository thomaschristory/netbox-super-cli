"""Recognize the NetBox Branching middleware's "this branch is unusable" 400s.

The middleware answers a request whose `X-NetBox-Branch` names a merged,
archived or deleted branch with a plain-text 400 (Django's
`HttpResponseBadRequest`), before any view runs. Only those exact bodies are
matched, so a validation 400 (JSON) is never mistaken for one.
"""

from __future__ import annotations

import re

from nsc.branching.errors import BranchUnusableError
from nsc.http.errors import NetBoxAPIError

_BAD_REQUEST = 400
_MISSING = re.compile(r"Invalid branch identifier")
_NOT_READY = re.compile(r"Selected branch is not ready\.?")
# The plugin's own BranchNotReady text, which names the status; current
# releases replace it with the generic message above, but it is matched in case
# a release passes it through.
_NOT_READY_WITH_STATUS = re.compile(
    r"Branch .+ is not ready for use \(status: (?P<status>[\w-]+)\)"
)


def branch_unusable_error(exc: NetBoxAPIError, branch: str | None) -> BranchUnusableError | None:
    """The branch-state error behind `exc`, or None if it is any other failure.

    `branch` is the active branch's name; without one no request carried the
    branch header, so the middleware cannot have produced the error.
    """
    if branch is None or exc.status_code != _BAD_REQUEST:
        return None
    body = (exc.body or "").strip()
    if _MISSING.fullmatch(body):
        return BranchUnusableError(branch, status=None, missing=True)
    if _NOT_READY.fullmatch(body):
        return BranchUnusableError(branch, status=None)
    match = _NOT_READY_WITH_STATUS.fullmatch(body)
    if match:
        return BranchUnusableError(branch, status=match["status"])
    return None
