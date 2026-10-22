"""Unit tests for the OS keyring adapter (always against a fake backend)."""

from __future__ import annotations

import pytest

from nsc.auth.keyring_store import (
    SERVICE_NAME,
    KeyringStoreError,
    get_secret,
    resolve_token,
    set_secret,
)
from nsc.config.models import KeyringRef, Profile


def _profile(token: str | KeyringRef | None) -> Profile:
    return Profile(name="prod", url="https://nb.example/", token=token)  # type: ignore[arg-type]


def test_set_then_get_uses_nsc_service(fake_keyring: dict[tuple[str, str], str]) -> None:
    set_secret("my-token", "T123")
    assert fake_keyring == {(SERVICE_NAME, "my-token"): "T123"}
    assert get_secret("my-token") == "T123"


def test_resolve_token_passes_plain_strings_through() -> None:
    assert resolve_token(_profile("plain")) == "plain"
    assert resolve_token(_profile(None)) is None


def test_resolve_token_reads_keyring_reference(
    fake_keyring: dict[tuple[str, str], str],
) -> None:
    fake_keyring[(SERVICE_NAME, "my-token")] = "T123"
    assert resolve_token(_profile(KeyringRef("my-token"))) == "T123"


@pytest.mark.usefixtures("fake_keyring")
def test_missing_entry_raises_actionable_error() -> None:
    with pytest.raises(KeyringStoreError) as excinfo:
        resolve_token(_profile(KeyringRef("absent")))
    message = str(excinfo.value)
    assert "absent" in message
    assert "nsc login --rotate --profile prod --store keyring" in message
    assert excinfo.value.keyring_name == "absent"


@pytest.mark.usefixtures("no_keyring")
def test_no_backend_raises_keyring_store_error_on_read() -> None:
    with pytest.raises(KeyringStoreError, match="no usable OS keyring backend"):
        get_secret("anything")


@pytest.mark.usefixtures("no_keyring")
def test_no_backend_raises_keyring_store_error_on_write() -> None:
    with pytest.raises(KeyringStoreError, match="no usable OS keyring backend"):
        set_secret("anything", "T123")
