"""Tests for the pre-flight authentication probe."""

from __future__ import annotations

import pytest
import respx

from nsc.auth.verify import VerifyError, VerifyResult, verify
from nsc.config.models import KeyringRef, Profile


def _profile(token: str = "T" * 40) -> Profile:
    return Profile(name="test", url="https://nb.example/", token=token)


def _status_ok(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get("https://nb.example/api/status/").respond(200, json={"netbox-version": "4.5.9"})


def _token(user: str, *, key: str | None = None, tid: int = 1) -> dict[str, object]:
    return {"id": tid, "version": 2, "key": key, "user": {"username": user, "id": tid}}


def _v1_token(user: str, *, plaintext: str | None = None, tid: int = 1) -> dict[str, object]:
    """A v1 row in the NetBox 4.5+ shape: `key` is the v2 id (null), plaintext is `token`."""
    row: dict[str, object] = {
        "id": tid,
        "version": 1,
        "key": None,
        "user": {"username": user, "id": tid},
    }
    if plaintext is not None:
        row["token"] = plaintext
    return row


def test_verify_happy_path_returns_username_and_version(httpx2_mock: respx.Router) -> None:
    _status_ok(httpx2_mock)
    httpx2_mock.get("https://nb.example/api/users/tokens/").respond(
        200,
        json={"count": 1, "next": None, "results": [_v1_token("alice")]},
    )
    result = verify(_profile())
    assert isinstance(result, VerifyResult)
    assert result.username == "alice"
    assert result.netbox_version == "4.5.9"


def test_verify_returns_none_username_when_token_list_is_empty(
    httpx2_mock: respx.Router,
) -> None:
    _status_ok(httpx2_mock)
    httpx2_mock.get("https://nb.example/api/users/tokens/").respond(
        200, json={"count": 0, "next": None, "results": []}
    )
    result = verify(_profile())
    assert result.username is None
    assert result.netbox_version == "4.5.9"


def test_verify_v1_does_not_report_arbitrary_token_owner(httpx2_mock: respx.Router) -> None:
    """Regression for #150: an admin sees other users' tokens; the first is not "me"."""
    _status_ok(httpx2_mock)
    httpx2_mock.get("https://nb.example/api/users/tokens/").respond(
        200,
        json={
            "count": 2,
            "next": None,
            "results": [_v1_token("coworker", tid=1), _v1_token("me", tid=2)],
        },
    )
    result = verify(_profile())
    assert result.username is None


def test_verify_v1_matches_retrievable_token_client_side(httpx2_mock: respx.Router) -> None:
    token = "a" * 40
    _status_ok(httpx2_mock)
    route = httpx2_mock.get("https://nb.example/api/users/tokens/").respond(
        200,
        json={
            "count": 2,
            "next": None,
            "results": [
                _v1_token("coworker", plaintext="b" * 40, tid=1),
                _v1_token("me", plaintext=token, tid=2),
            ],
        },
    )
    result = verify(_profile(token))
    assert result.username == "me"
    assert token not in str(route.calls.last.request.url)


def test_verify_v1_matches_legacy_key_field_on_pre_45_netbox(httpx2_mock: respx.Router) -> None:
    token = "a" * 40
    _status_ok(httpx2_mock)
    httpx2_mock.get("https://nb.example/api/users/tokens/").respond(
        200,
        json={
            "count": 2,
            "next": None,
            "results": [
                {"id": 1, "key": "b" * 40, "user": {"username": "coworker", "id": 1}},
                {"id": 2, "key": token, "user": {"username": "me", "id": 2}},
            ],
        },
    )
    assert verify(_profile(token)).username == "me"


def test_verify_v1_unknown_when_plaintext_hidden_and_owners_differ(
    httpx2_mock: respx.Router,
) -> None:
    _status_ok(httpx2_mock)
    httpx2_mock.get("https://nb.example/api/users/tokens/").respond(
        200,
        json={
            "count": 3,
            "next": None,
            "results": [
                _v1_token("coworker", tid=1),
                _v1_token("me", tid=2),
                _v1_token("other", tid=3),
            ],
        },
    )
    assert verify(_profile("a" * 40)).username is None


def test_verify_v1_does_not_match_v2_row_whose_key_equals_token(
    httpx2_mock: respx.Router,
) -> None:
    token = "a" * 40
    _status_ok(httpx2_mock)
    httpx2_mock.get("https://nb.example/api/users/tokens/").respond(
        200,
        json={
            "count": 2,
            "next": None,
            "results": [_token("coworker", key=token, tid=1), _v1_token("me", tid=2)],
        },
    )
    assert verify(_profile(token)).username is None


def test_verify_v1_exact_match_wins_over_pagination(httpx2_mock: respx.Router) -> None:
    token = "a" * 40
    _status_ok(httpx2_mock)
    httpx2_mock.get("https://nb.example/api/users/tokens/").respond(
        200,
        json={
            "count": 500,
            "next": "https://nb.example/api/users/tokens/?limit=100&offset=100",
            "results": [
                _v1_token("coworker", plaintext="b" * 40, tid=1),
                _v1_token("me", plaintext=token, tid=2),
            ],
        },
    )
    assert verify(_profile(token)).username == "me"


def test_verify_v1_single_owner_across_visible_tokens(httpx2_mock: respx.Router) -> None:
    _status_ok(httpx2_mock)
    httpx2_mock.get("https://nb.example/api/users/tokens/").respond(
        200,
        json={
            "count": 2,
            "next": None,
            "results": [_v1_token("me", tid=1), _v1_token("me", tid=2)],
        },
    )
    assert verify(_profile()).username == "me"


def test_verify_v1_single_owner_heuristic_refused_when_paginated(
    httpx2_mock: respx.Router,
) -> None:
    _status_ok(httpx2_mock)
    httpx2_mock.get("https://nb.example/api/users/tokens/").respond(
        200,
        json={
            "count": 500,
            "next": "https://nb.example/api/users/tokens/?limit=100&offset=100",
            "results": [_v1_token("coworker", tid=1)],
        },
    )
    assert verify(_profile()).username is None


def test_verify_v2_filters_by_key_id(httpx2_mock: respx.Router) -> None:
    secret = "s" * 40
    _status_ok(httpx2_mock)
    route = httpx2_mock.get(
        "https://nb.example/api/users/tokens/", params={"key": "abc123"}
    ).respond(
        200,
        json={"count": 1, "next": None, "results": [_token("me", key="abc123")]},
    )
    result = verify(_profile(f"nbt_abc123.{secret}"))
    assert result.username == "me"
    assert route.called
    assert secret not in str(route.calls.last.request.url)


def test_verify_v2_unknown_when_no_row_matches_key_id(httpx2_mock: respx.Router) -> None:
    _status_ok(httpx2_mock)
    httpx2_mock.get("https://nb.example/api/users/tokens/", params={"key": "abc123"}).respond(
        200,
        json={
            "count": 2,
            "next": None,
            "results": [_token("coworker", key="zzz", tid=1), _token("me", key="other", tid=2)],
        },
    )
    assert verify(_profile("nbt_abc123." + "s" * 40)).username is None


def test_verify_v2_unknown_when_key_id_matches_multiple_rows(httpx2_mock: respx.Router) -> None:
    _status_ok(httpx2_mock)
    route = httpx2_mock.get(
        "https://nb.example/api/users/tokens/", params={"key": "abc123"}
    ).respond(
        200,
        json={
            "count": 2,
            "next": None,
            "results": [_token("coworker", key="abc123", tid=1), _token("me", key="abc123", tid=2)],
        },
    )
    assert verify(_profile("nbt_abc123." + "s" * 40)).username is None
    assert route.called


def test_verify_keyring_ref_identifies_user_from_resolved_token(
    httpx2_mock: respx.Router, fake_keyring: dict[tuple[str, str], str]
) -> None:
    fake_keyring[("nsc", "prod")] = "nbt_abc123." + "s" * 40
    _status_ok(httpx2_mock)
    route = httpx2_mock.get(
        "https://nb.example/api/users/tokens/", params={"key": "abc123"}
    ).respond(
        200,
        json={"count": 1, "next": None, "results": [_token("me", key="abc123")]},
    )
    profile = Profile(name="test", url="https://nb.example/", token=KeyringRef("prod"))
    assert verify(profile).username == "me"
    assert route.called


def test_verify_raises_on_status_endpoint_4xx(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get("https://nb.example/api/status/").respond(401, json={})
    with pytest.raises(VerifyError) as excinfo:
        verify(_profile())
    err = excinfo.value
    assert err.status_code == 401
    assert err.user_check_status is None  # auth probe never reached


def test_verify_raises_on_token_probe_4xx_after_status_ok(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get("https://nb.example/api/status/").respond(200, json={"netbox-version": "4.5.9"})
    httpx2_mock.get("https://nb.example/api/users/tokens/").respond(
        403, json={"detail": "forbidden"}
    )
    with pytest.raises(VerifyError) as excinfo:
        verify(_profile())
    err = excinfo.value
    assert err.status_code == 403
    assert err.user_check_status == 403  # spec §4.2 distinguishing detail


def test_verify_raises_on_transport_error(httpx2_mock: respx.Router) -> None:
    httpx2_mock.get("https://nb.example/api/status/").mock(side_effect=ConnectionError("nope"))
    with pytest.raises(VerifyError) as excinfo:
        verify(_profile())
    assert excinfo.value.status_code is None
    assert "nope" in str(excinfo.value)


def test_verify_rejects_profile_with_no_token() -> None:
    with pytest.raises(VerifyError, match="token"):
        verify(Profile(name="x", url="https://nb.example/", token=None))
