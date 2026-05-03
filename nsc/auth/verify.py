"""Pre-flight verification of a profile's URL+token.

`verify(profile)` issues two probes against the candidate NetBox:

* `GET /api/status/` — confirms the URL is a NetBox and reports the version.
* `GET /api/users/me/` — confirms the token is accepted and reports the user.

Both must succeed. Either failure raises `VerifyError`; the caller maps the
exception to an `auth_error` envelope (`ErrorType.AUTH`, exit 8). Login is not
audited — `verify` deliberately bypasses `NetBoxClient` to keep the pre-flight
out of `audit.jsonl`. There is no retry loop: a single failed probe fails fast.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel, ConfigDict

from nsc.config.models import Profile

_DEFAULT_TIMEOUT = 10.0


class VerifyResult(BaseModel):
    """The success-shape of a pre-flight verification."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    username: str
    netbox_version: str


class VerifyError(Exception):
    """Pre-flight verification failed.

    `status_code` is the HTTP status of the failing probe, or `None` when the
    failure was a transport error (connection refused, TLS, DNS, etc.).
    `user_check_status` is set to the same status as `status_code` when the
    `/api/users/me/` probe was the one that failed (i.e. `/api/status/` returned
    2xx but the token was rejected by the user-info endpoint). This distinguishes
    "wrong URL / NetBox down" from "URL fine, token rejected".
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        user_check_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.user_check_status = user_check_status

    def __str__(self) -> str:
        return self.message


def verify(profile: Profile, *, timeout: float = _DEFAULT_TIMEOUT) -> VerifyResult:
    """Confirm `profile`'s URL+token reach an authenticated NetBox.

    Raises `VerifyError` on any failure. Returns a `VerifyResult` on success.
    """
    if not profile.token:
        raise VerifyError(message="profile has no token; cannot verify")
    base = str(profile.url).rstrip("/")
    headers = {
        "Authorization": f"Token {profile.token}",
        "Accept": "application/json",
    }
    with httpx.Client(
        base_url=base,
        headers=headers,
        verify=profile.verify_ssl,
        timeout=timeout,
    ) as client:
        version = _probe_status(client)
        username = _probe_users_me(client)
    return VerifyResult(username=username, netbox_version=version)


def _probe_status(client: httpx.Client) -> str:
    try:
        response = client.get("/api/status/")
    except (httpx.RequestError, OSError) as exc:
        raise VerifyError(message=f"could not reach NetBox: {exc}") from exc
    if not response.is_success:
        raise VerifyError(
            message=f"NetBox /api/status/ returned {response.status_code}",
            status_code=response.status_code,
        )
    body = _safe_json(response)
    version = body.get("netbox-version") if isinstance(body, dict) else None
    return str(version) if version else "unknown"


def _probe_users_me(client: httpx.Client) -> str:
    try:
        response = client.get("/api/users/me/")
    except (httpx.RequestError, OSError) as exc:
        raise VerifyError(message=f"users/me probe failed: {exc}") from exc
    if not response.is_success:
        raise VerifyError(
            message=(
                f"NetBox accepted the URL but rejected the token "
                f"(/api/users/me/ returned {response.status_code})"
            ),
            status_code=response.status_code,
            user_check_status=response.status_code,
        )
    body = _safe_json(response)
    username = body.get("username") if isinstance(body, dict) else None
    if not username:
        raise VerifyError(
            message="users/me returned no username field",
            status_code=response.status_code,
            user_check_status=response.status_code,
        )
    return str(username)


def _safe_json(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return None
