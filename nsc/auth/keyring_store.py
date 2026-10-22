"""OS keyring adapter backing the `!keyring NAME` config tag.

Entries live under the fixed service `SERVICE_NAME` with the tag's NAME as the
keyring username, so `!keyring prod` maps to (service="nsc", username="prod").

`keyring` is imported lazily: its backend discovery walks entry points, which
is too slow for the CLI startup path and pointless for commands that never
send a request.
"""

from __future__ import annotations

from nsc.config.models import KeyringRef, Profile

SERVICE_NAME = "nsc"


class KeyringStoreError(Exception):
    """The OS keyring is unavailable or lacks the requested entry."""

    def __init__(self, message: str, *, keyring_name: str) -> None:
        super().__init__(message)
        self.message = message
        self.keyring_name = keyring_name

    def __str__(self) -> str:
        return self.message


def _no_backend_message(name: str, exc: Exception) -> str:
    return (
        f"no usable OS keyring backend for entry {name!r} (service {SERVICE_NAME!r}): {exc}. "
        "Use `!env` indirection instead, or install a keyring backend "
        "(see https://pypi.org/project/keyring)."
    )


def get_secret(name: str) -> str | None:
    """Return the stored secret for `name`, or None when no entry exists."""
    try:
        import keyring  # noqa: PLC0415  # deferred: see module docstring.
        from keyring.errors import KeyringError  # noqa: PLC0415
    except ImportError as exc:
        raise KeyringStoreError(_no_backend_message(name, exc), keyring_name=name) from exc
    try:
        return keyring.get_password(SERVICE_NAME, name)
    except KeyringError as exc:
        raise KeyringStoreError(_no_backend_message(name, exc), keyring_name=name) from exc


def set_secret(name: str, secret: str) -> None:
    """Store `secret` under `name`, replacing any existing entry."""
    try:
        import keyring  # noqa: PLC0415  # deferred: see module docstring.
        from keyring.errors import KeyringError  # noqa: PLC0415
    except ImportError as exc:
        raise KeyringStoreError(_no_backend_message(name, exc), keyring_name=name) from exc
    try:
        keyring.set_password(SERVICE_NAME, name, secret)
    except KeyringError as exc:
        raise KeyringStoreError(_no_backend_message(name, exc), keyring_name=name) from exc


def resolve_token(profile: Profile) -> str | None:
    """Return `profile`'s usable token string, dereferencing `!keyring` entries."""
    token = profile.token
    if not isinstance(token, KeyringRef):
        return token
    secret = get_secret(token.name)
    if secret is None:
        raise KeyringStoreError(
            f"no OS keyring entry {token.name!r} (service {SERVICE_NAME!r}) for profile "
            f"{profile.name!r}; store one with "
            f"`nsc login --rotate --profile {profile.name} --store keyring`.",
            keyring_name=token.name,
        )
    return secret
