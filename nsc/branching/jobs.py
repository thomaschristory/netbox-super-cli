from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

from nsc.branching.errors import BranchJobFailedError, BranchJobTimeoutError
from nsc.branching.models import JOBS_PATH, Branch, choice_value

if TYPE_CHECKING:
    from nsc.http.client import NetBoxClient

_FIRST_DELAY = 1.0
_MAX_DELAY = 10.0
JOB_DONE = "completed"
JOB_FAILED = frozenset({"errored", "failed"})

Sleep = Callable[[float], None]
Clock = Callable[[], float]


def backoff_delays() -> Iterator[float]:
    delay = _FIRST_DELAY
    while True:
        yield delay
        delay = min(delay * 2, _MAX_DELAY)


def job_status(job: dict[str, Any]) -> str | None:
    value = choice_value(job.get("status"))
    return value if isinstance(value, str) else None


def wait_for_job(
    client: NetBoxClient,
    job: dict[str, Any],
    *,
    branch: Branch,
    timeout: float,
    sleep: Sleep = time.sleep,
    clock: Clock = time.monotonic,
) -> dict[str, Any]:
    # Poll by id, not the absolute `url`: the client's base URL already carries
    # any BASE_PATH, so reusing the URL's path would double-prefix it.
    job_id = job.get("id")
    deadline = clock() + timeout
    delays = backoff_delays()
    while True:
        current = client.get(f"{JOBS_PATH}{job_id}/")
        status = job_status(current)
        if status == JOB_DONE:
            return current
        if status in JOB_FAILED:
            raise BranchJobFailedError(branch.name, current)
        if clock() >= deadline:
            raise BranchJobTimeoutError(branch.name, job_id)
        sleep(next(delays))
