"""Pre-flight verification of a profile's URL+token.

`verify(profile)` issues two probes against the candidate NetBox:

* `GET /api/status/` — confirms the URL is a NetBox and reports the version.
* `GET /api/users/tokens/` — confirms the token is accepted (the endpoint
  requires authentication) and, where it can be done reliably, identifies the
  calling user from the token that was presented. NetBox exposes no "current
  user" endpoint, so identity is best-effort: when it cannot be pinned down,
  `VerifyResult.username` is `None` rather than a guess (see #150).

Both must succeed. Either failure raises `VerifyError`; the caller maps the
exception to an `auth_error` envelope (`ErrorType.AUTH`, exit 8). Login is not
audited — `verify` deliberately bypasses `NetBoxClient` to keep the pre-flight
out of `audit.jsonl`. There is no retry loop: a single failed probe fails fast.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from nsc.auth.keyring_store import resolve_token
from nsc.config.models import Profile

if TYPE_CHECKING:
    import httpx2

_DEFAULT_TIMEOUT = 10.0


class VerifyResult(BaseModel):
    """The success-shape of a pre-flight verification."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    username: str | None
    netbox_version: str


class VerifyError(Exception):
    """Pre-flight verification failed.

    `status_code` is the HTTP status of the failing probe, or `None` when the
    failure was a transport error (connection refused, TLS, DNS, etc.).
    `user_check_status` is set to the same status as `status_code` when the
    auth probe (`/api/users/tokens/`) was the one that failed (i.e. `/api/status/`
    returned 2xx but the token was rejected). This distinguishes
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
    import httpx2  # noqa: PLC0415  # deferred: keeps httpx2 off the CLI-startup path.

    token = resolve_token(profile)
    if not token:
        raise VerifyError(message="profile has no token; cannot verify")
    base = str(profile.url).rstrip("/")
    headers = {
        "Authorization": f"Token {token}",
        "Accept": "application/json",
    }
    with httpx2.Client(
        base_url=base,
        headers=headers,
        verify=profile.verify_ssl,
        timeout=timeout,
    ) as client:
        version = _probe_status(client)
        username = _probe_identity(client, token)
    return VerifyResult(username=username, netbox_version=version)


def _probe_status(client: httpx2.Client) -> str:
    import httpx2  # noqa: PLC0415  # deferred: keeps httpx2 off the CLI-startup path.

    try:
        response = client.get("/api/status/")
    except (httpx2.RequestError, OSError) as exc:
        raise VerifyError(message=f"could not reach NetBox: {exc}") from exc
    if not response.is_success:
        raise VerifyError(
            message=f"NetBox /api/status/ returned {response.status_code}",
            status_code=response.status_code,
        )
    body = _safe_json(response)
    version = body.get("netbox-version") if isinstance(body, dict) else None
    return str(version) if version else "unknown"


_V2_PREFIX = "nbt_"
_PAGE_LIMIT = 100


def _probe_identity(client: httpx2.Client, token: str) -> str | None:
    """Verify the token and identify the calling user when that is unambiguous.

    The token list is visible across users to admins, so its first row is *not*
    the caller in general (#150). Instead:

    * v2 (`nbt_<key>.<secret>`): filter by the non-secret key id. Key ids are
      unique, so a single matching row is the presented token.
    * v1: the plaintext must never go in a query string (proxy/access logs), so
      fetch one page and match the plaintext client-side where NetBox exposes it
      (`ALLOW_TOKEN_RETRIEVAL`): in `token` on 4.5+, in `key` on older servers.
      Only v1 rows are compared. Failing that, if every token on a complete
      page belongs to one user, the caller's own token is among them unless
      object permissions hide it, which is rare enough to accept.
    """
    import httpx2  # noqa: PLC0415  # deferred: keeps httpx2 off the CLI-startup path.

    params: dict[str, str | int] = {"limit": _PAGE_LIMIT}
    key_id = _v2_key_id(token)
    if key_id is not None:
        params["key"] = key_id
    try:
        response = client.get("/api/users/tokens/", params=params)
    except (httpx2.RequestError, OSError) as exc:
        raise VerifyError(message=f"token probe failed: {exc}") from exc
    if not response.is_success:
        raise VerifyError(
            message=(
                f"NetBox accepted the URL but rejected the token "
                f"(/api/users/tokens/ returned {response.status_code})"
            ),
            status_code=response.status_code,
            user_check_status=response.status_code,
        )
    body = _safe_json(response)
    if not isinstance(body, dict):
        return None
    rows = [r for r in body.get("results") or [] if isinstance(r, dict)]
    if key_id is not None:
        matches = [r for r in rows if r.get("key") == key_id]
        return _username(matches[0]) if len(matches) == 1 else None
    exact = [r for r in rows if _v1_plaintext_matches(r, token)]
    if len(exact) == 1:
        return _username(exact[0])
    if body.get("next"):
        return None
    owners = {_username(r) for r in rows}
    if len(owners) == 1:
        return owners.pop()
    return None


def _v1_plaintext_matches(row: dict[str, object], token: str) -> bool:
    # NetBox 4.5+ returns a retrievable v1 plaintext in `token` (`key` is the v2
    # id, null for v1); older servers put the plaintext in `key`.
    if row.get("version") not in (1, None):
        return False
    return row.get("token") == token or row.get("key") == token


def _v2_key_id(token: str) -> str | None:
    if not token.startswith(_V2_PREFIX):
        return None
    key_id, sep, _ = token[len(_V2_PREFIX) :].partition(".")
    return key_id if sep and key_id else None


def _username(row: dict[str, object]) -> str | None:
    user = row.get("user")
    if isinstance(user, dict):
        username = user.get("username")
        if username:
            return str(username)
    return None


def describe_identity(username: str | None) -> str:
    return f"authenticated as {username}" if username else "authenticated (user unknown)"


def _safe_json(response: httpx2.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return None
