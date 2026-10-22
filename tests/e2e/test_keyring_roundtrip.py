"""Live-NetBox e2e: `nsc login --store keyring` then a request, via the real OS keyring.

Skipped unless the host has a usable keyring backend (Keychain, Secret Service,
Credential Manager). Headless CI runners usually have none, so this test is
mostly exercised on developer machines. The entry it creates uses a unique name
and is deleted on teardown.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from nsc.auth.keyring_store import SERVICE_NAME


def _usable_backend() -> bool:
    try:
        import keyring  # noqa: PLC0415
        from keyring.backends import fail  # noqa: PLC0415
    except ImportError:
        return False
    backend = keyring.get_keyring()
    return not isinstance(backend, fail.Keyring) and backend.priority > 0


pytestmark = pytest.mark.skipif(not _usable_backend(), reason="no usable OS keyring backend")


@pytest.fixture
def keyring_name() -> Iterator[str]:
    import keyring  # noqa: PLC0415
    from keyring.errors import PasswordDeleteError  # noqa: PLC0415

    name = f"nsc-e2e-{uuid.uuid4().hex[:12]}"
    yield name
    with contextlib.suppress(PasswordDeleteError):
        keyring.delete_password(SERVICE_NAME, name)


def test_keyring_round_trip_never_writes_plaintext(
    run_nsc: Callable[..., Any],
    nsc_url: str,
    nsc_token: str,
    tmp_nsc_home: Path,
    keyring_name: str,
) -> None:
    # Blank NSC_TOKEN so the request below can only authenticate via the keyring.
    no_env_token = {"NSC_TOKEN": "", "NSC_URL": ""}
    created = run_nsc(
        "login",
        "--new",
        "--profile",
        "e2e",
        "--url",
        nsc_url,
        "--store",
        "keyring",
        "--keyring-name",
        keyring_name,
        env=no_env_token,
        input=f"{nsc_token}\nn\n",
    )
    assert created.returncode == 0, created.stdout + created.stderr

    config_path = tmp_nsc_home / "config.yaml"
    assert f"!keyring {keyring_name}" in config_path.read_text(encoding="utf-8")
    assert nsc_token not in config_path.read_text(encoding="utf-8")

    listed = run_nsc("dcim", "devices", "list", "--output", "json", env=no_env_token)
    assert listed.returncode == 0, listed.stdout + listed.stderr
    assert isinstance(json.loads(listed.stdout), list)
    assert nsc_token not in config_path.read_text(encoding="utf-8")
