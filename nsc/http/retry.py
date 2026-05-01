"""Per-method retry policy + error classification (Phase 3a).

Pure functions only. The retry *loop* lives in `NetBoxClient`; this module
decides whether to keep going.
"""

from __future__ import annotations

import random
from enum import Enum

import httpx
from pydantic import BaseModel, ConfigDict

from nsc.model.command_model import HttpMethod


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RetryPolicy(_Frozen):
    max_attempts: int = 3
    base_delay: float = 0.5
    jitter: float = 0.25
    retry_on_5xx: bool
    retry_on_connect: bool


class ErrorClass(Enum):
    """Classification of a transport-layer exception."""

    CONNECT = "connect"  # provably no-op (request never sent)
    READ_TIMEOUT = "read_timeout"  # bytes sent, server may have processed
    TRANSPORT_AMBIGUOUS = "transport_ambig"  # could be either; treat as may-have-sent


_READ_METHODS = {HttpMethod.GET, HttpMethod.HEAD, HttpMethod.OPTIONS}

_5XX_MIN = 500
_5XX_MAX = 600


def policy_for_method(method: HttpMethod) -> RetryPolicy:
    if method in _READ_METHODS:
        return RetryPolicy(retry_on_5xx=True, retry_on_connect=True)
    return RetryPolicy(retry_on_5xx=False, retry_on_connect=True)


def classify_error(exc: BaseException) -> ErrorClass:
    """Map an httpx transport exception to a retry-relevant class."""
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return ErrorClass.CONNECT
    if isinstance(exc, httpx.ReadTimeout):
        return ErrorClass.READ_TIMEOUT
    return ErrorClass.TRANSPORT_AMBIGUOUS


def should_retry(
    policy: RetryPolicy,
    *,
    attempt: int,
    status_code: int | None,
    error_class: ErrorClass | None,
) -> bool:
    """Should we attempt request `attempt + 1`?

    Args:
        attempt: The 1-indexed attempt that just finished.
        status_code: HTTP status from the response, or None if no response.
        error_class: The transport classification, or None if a response arrived.
    """
    if attempt >= policy.max_attempts:
        return False
    if error_class is ErrorClass.CONNECT:
        return policy.retry_on_connect
    if error_class in (ErrorClass.READ_TIMEOUT, ErrorClass.TRANSPORT_AMBIGUOUS):
        return False  # never retry possibly-already-sent writes; reads don't either (safety)
    if status_code is not None and _5XX_MIN <= status_code < _5XX_MAX:
        return policy.retry_on_5xx
    return False


def backoff_delay(policy: RetryPolicy, *, attempt: int) -> float:
    """Exponential backoff with ± jitter%, in seconds."""
    base: float = policy.base_delay * (2 ** (attempt - 1))
    if policy.jitter == 0.0:
        return base
    span: float = base * policy.jitter
    return float(base + random.uniform(-span, span))
