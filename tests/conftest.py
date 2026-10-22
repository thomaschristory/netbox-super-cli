"""Shared pytest fixtures."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def bundled_schemas_dir() -> Path:
    return REPO_ROOT / "nsc" / "schemas" / "bundled"


@pytest.fixture
def fixture_response() -> Callable[[str], dict[str, Any]]:
    def _load(name: str) -> dict[str, Any]:
        return json.loads((FIXTURES / "responses" / name).read_text(encoding="utf-8"))

    return _load


@pytest.fixture
def fixture_profile_yaml(tmp_path: Path) -> Path:
    src = (FIXTURES / "profiles" / "single_profile.yaml").read_text(encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    cfg = home / "config.yaml"
    cfg.write_text(src, encoding="utf-8")
    return home


@pytest.fixture
def fake_keyring() -> Iterator[dict[tuple[str, str], str]]:
    """Swap the process keyring for an in-memory backend; yields its store."""
    import keyring  # noqa: PLC0415
    from keyring.backend import KeyringBackend  # noqa: PLC0415
    from keyring.errors import PasswordDeleteError  # noqa: PLC0415

    store: dict[tuple[str, str], str] = {}

    class _MemoryKeyring(KeyringBackend):
        priority = 1  # type: ignore[assignment]

        def get_password(self, service: str, username: str) -> str | None:
            return store.get((service, username))

        def set_password(self, service: str, username: str, password: str) -> None:
            store[(service, username)] = password

        def delete_password(self, service: str, username: str) -> None:
            if store.pop((service, username), None) is None:
                raise PasswordDeleteError(username)

    previous = keyring.get_keyring()
    keyring.set_keyring(_MemoryKeyring())
    try:
        yield store
    finally:
        keyring.set_keyring(previous)


@pytest.fixture
def no_keyring() -> Iterator[None]:
    """Swap the process keyring for keyring's always-failing backend."""
    import keyring  # noqa: PLC0415
    from keyring.backends import fail  # noqa: PLC0415

    previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())
    try:
        yield
    finally:
        keyring.set_keyring(previous)
