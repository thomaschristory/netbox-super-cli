"""Live-NetBox e2e coverage for `nsc login`.

Exercises the onboarding verbs against the docker-compose stack in
`tests/e2e/docker-compose.yml`. Uses `run_nsc` for subprocess parity with end
users; `netbox_client` is reserved for state assertions and token minting.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest


def _seed_minimal_config(home: Path, name: str, url: str, token: str) -> None:
    (home / "config.yaml").write_text(
        f"default_profile: {name}\nprofiles:\n  {name}:\n    url: {url}\n    token: {token}\n",
        encoding="utf-8",
    )


def test_login_bare_against_live_netbox(
    run_nsc: Callable[..., object],
    nsc_url: str,
    nsc_token: str,
    tmp_nsc_home: Path,
) -> None:
    _seed_minimal_config(tmp_nsc_home, "e2e", nsc_url, nsc_token)
    result = run_nsc("login", "--profile", "e2e")
    assert result.returncode == 0, result.stdout + result.stderr  # type: ignore[attr-defined]
    assert "authenticated as" in result.stdout  # type: ignore[attr-defined]
    assert "NetBox" in result.stdout  # type: ignore[attr-defined]


def test_login_new_creates_profile_against_live_netbox(
    run_nsc: Callable[..., object],
    nsc_url: str,
    nsc_token: str,
    tmp_nsc_home: Path,
) -> None:
    result = run_nsc(
        "login",
        "--new",
        "--profile",
        "fresh",
        "--url",
        nsc_url,
        "--store",
        "plaintext",
        input=f"{nsc_token}\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr  # type: ignore[attr-defined]
    body = (tmp_nsc_home / "config.yaml").read_text(encoding="utf-8")
    assert "fresh:" in body
    assert "default_profile: fresh" in body


def test_login_rotate_replaces_token_against_live_netbox(
    run_nsc: Callable[..., object],
    netbox_client: httpx.Client,
    nsc_url: str,
    nsc_token: str,
    tmp_nsc_home: Path,
) -> None:
    _seed_minimal_config(tmp_nsc_home, "e2e", nsc_url, nsc_token)
    me = netbox_client.get("/api/users/users/me/")
    me.raise_for_status()
    user_id = me.json()["id"]
    minted = netbox_client.post(
        "/api/users/tokens/",
        json={"user": user_id, "description": "nsc e2e rotate"},
    )
    if minted.status_code in (404, 405):
        pytest.skip("this NetBox build does not expose user-token minting")
    minted.raise_for_status()
    minted_payload = minted.json()
    new_token = minted_payload["key"]

    try:
        result = run_nsc(
            "login",
            "--rotate",
            "--profile",
            "e2e",
            input=f"{new_token}\n",
        )
        assert result.returncode == 0, result.stdout + result.stderr  # type: ignore[attr-defined]
        body = (tmp_nsc_home / "config.yaml").read_text(encoding="utf-8")
        assert f"token: {new_token}" in body
        assert nsc_token not in body
    finally:
        minted_id = minted_payload["id"]
        netbox_client.delete(f"/api/users/tokens/{minted_id}/")


def test_login_with_bad_token_returns_auth_envelope(
    run_nsc: Callable[..., object],
    nsc_url: str,
    tmp_nsc_home: Path,
) -> None:
    _seed_minimal_config(tmp_nsc_home, "e2e", nsc_url, "0" * 40)
    result = run_nsc("login", "--profile", "e2e")
    assert result.returncode == 8, result.stdout + result.stderr  # type: ignore[attr-defined]
    payload_text = result.stdout.strip() or result.stderr.strip()  # type: ignore[attr-defined]
    payload = json.loads(payload_text.splitlines()[-1])
    assert payload["type"] == "auth"
    assert payload["status_code"] in (401, 403)
