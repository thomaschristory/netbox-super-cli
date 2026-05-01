"""RetryPolicy + classify_error + should_retry pure functions (Phase 3a)."""

from __future__ import annotations

import httpx
import pytest

from nsc.http.retry import (
    ErrorClass,
    RetryPolicy,
    backoff_delay,
    classify_error,
    policy_for_method,
    should_retry,
)
from nsc.model.command_model import HttpMethod


def _request(method: str = "GET") -> httpx.Request:
    return httpx.Request(method, "https://nb.example/api/x/")


# --- policy_for_method -----------------------------------------------------------------


@pytest.mark.parametrize("method", [HttpMethod.GET, HttpMethod.HEAD, HttpMethod.OPTIONS])
def test_read_methods_retry_on_5xx_and_connect(method: HttpMethod) -> None:
    p = policy_for_method(method)
    assert p.retry_on_5xx is True
    assert p.retry_on_connect is True


@pytest.mark.parametrize(
    "method",
    [HttpMethod.POST, HttpMethod.PATCH, HttpMethod.PUT, HttpMethod.DELETE],
)
def test_write_methods_never_retry_5xx_but_retry_connect(method: HttpMethod) -> None:
    p = policy_for_method(method)
    assert p.retry_on_5xx is False
    assert p.retry_on_connect is True


def test_default_attempts_and_backoff() -> None:
    p = policy_for_method(HttpMethod.GET)
    assert p.max_attempts == 3
    assert p.base_delay == pytest.approx(0.5)
    assert 0.0 <= p.jitter <= 1.0


# --- classify_error --------------------------------------------------------------------


def test_classify_connect_error_provably_no_op() -> None:
    exc = httpx.ConnectError("nope", request=_request())
    assert classify_error(exc) is ErrorClass.CONNECT


def test_classify_connect_timeout_provably_no_op() -> None:
    exc = httpx.ConnectTimeout("slow", request=_request())
    assert classify_error(exc) is ErrorClass.CONNECT


def test_classify_read_timeout_NOT_connect() -> None:
    exc = httpx.ReadTimeout("late", request=_request())
    assert classify_error(exc) is ErrorClass.READ_TIMEOUT


def test_classify_remote_protocol_error_is_transport() -> None:
    exc = httpx.RemoteProtocolError("garbled", request=_request())
    assert classify_error(exc) is ErrorClass.TRANSPORT_AMBIGUOUS


# --- should_retry ----------------------------------------------------------------------


def test_should_retry_get_5xx_until_max_attempts() -> None:
    p = policy_for_method(HttpMethod.GET)
    assert should_retry(p, attempt=1, status_code=503, error_class=None) is True
    assert should_retry(p, attempt=2, status_code=503, error_class=None) is True
    assert should_retry(p, attempt=3, status_code=503, error_class=None) is False  # exhausted


def test_should_retry_post_5xx_never() -> None:
    p = policy_for_method(HttpMethod.POST)
    assert should_retry(p, attempt=1, status_code=503, error_class=None) is False


def test_should_retry_post_connect_yes_until_max() -> None:
    p = policy_for_method(HttpMethod.POST)
    assert should_retry(p, attempt=1, status_code=None, error_class=ErrorClass.CONNECT) is True
    assert should_retry(p, attempt=2, status_code=None, error_class=ErrorClass.CONNECT) is True
    assert should_retry(p, attempt=3, status_code=None, error_class=ErrorClass.CONNECT) is False


def test_should_retry_post_read_timeout_never() -> None:
    p = policy_for_method(HttpMethod.POST)
    assert (
        should_retry(p, attempt=1, status_code=None, error_class=ErrorClass.READ_TIMEOUT) is False
    )


def test_should_retry_post_transport_ambiguous_never() -> None:
    p = policy_for_method(HttpMethod.POST)
    assert (
        should_retry(p, attempt=1, status_code=None, error_class=ErrorClass.TRANSPORT_AMBIGUOUS)
        is False
    )


def test_should_retry_4xx_never_for_any_method() -> None:
    for m in HttpMethod:
        p = policy_for_method(m)
        assert should_retry(p, attempt=1, status_code=400, error_class=None) is False
        assert should_retry(p, attempt=1, status_code=404, error_class=None) is False
        assert should_retry(p, attempt=1, status_code=409, error_class=None) is False


# --- backoff_delay ---------------------------------------------------------------------


def test_backoff_delay_grows_exponentially_with_jitter_window() -> None:
    p = RetryPolicy(
        max_attempts=5, base_delay=1.0, jitter=0.0, retry_on_5xx=True, retry_on_connect=True
    )
    assert backoff_delay(p, attempt=1) == 1.0
    assert backoff_delay(p, attempt=2) == 2.0
    assert backoff_delay(p, attempt=3) == 4.0


def test_backoff_delay_with_jitter_stays_in_band() -> None:
    p = RetryPolicy(
        max_attempts=5, base_delay=1.0, jitter=0.25, retry_on_5xx=True, retry_on_connect=True
    )
    for _ in range(50):
        d = backoff_delay(p, attempt=2)
        assert 1.5 <= d <= 2.5
