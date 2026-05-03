"""Tests for the pre-flight authentication probe."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from nsc.auth.verify import VerifyError, VerifyResult, verify
from nsc.config.models import Profile


def _profile(token: str = "T" * 40) -> Profile:
    return Profile(name="test", url="https://nb.example/", token=token)


@respx.mock
def test_verify_happy_path_returns_username_and_version() -> None:
    respx.get("https://nb.example/api/status/").mock(
        return_value=Response(200, json={"netbox-version": "4.5.9"})
    )
    respx.get("https://nb.example/api/users/users/me/").mock(
        return_value=Response(200, json={"username": "alice", "id": 1})
    )
    result = verify(_profile())
    assert isinstance(result, VerifyResult)
    assert result.username == "alice"
    assert result.netbox_version == "4.5.9"


@respx.mock
def test_verify_raises_on_status_endpoint_4xx() -> None:
    respx.get("https://nb.example/api/status/").mock(return_value=Response(401, json={}))
    with pytest.raises(VerifyError) as excinfo:
        verify(_profile())
    err = excinfo.value
    assert err.status_code == 401
    assert err.user_check_status is None  # /users/me/ never reached


@respx.mock
def test_verify_raises_on_users_me_4xx_after_status_ok() -> None:
    respx.get("https://nb.example/api/status/").mock(
        return_value=Response(200, json={"netbox-version": "4.5.9"})
    )
    respx.get("https://nb.example/api/users/users/me/").mock(
        return_value=Response(403, json={"detail": "forbidden"})
    )
    with pytest.raises(VerifyError) as excinfo:
        verify(_profile())
    err = excinfo.value
    assert err.status_code == 403
    assert err.user_check_status == 403  # spec §4.2 distinguishing detail


@respx.mock
def test_verify_raises_on_transport_error() -> None:
    respx.get("https://nb.example/api/status/").mock(side_effect=ConnectionError("nope"))
    with pytest.raises(VerifyError) as excinfo:
        verify(_profile())
    assert excinfo.value.status_code is None
    assert "nope" in str(excinfo.value)


def test_verify_rejects_profile_with_no_token() -> None:
    with pytest.raises(VerifyError, match="token"):
        verify(Profile(name="x", url="https://nb.example/", token=None))
