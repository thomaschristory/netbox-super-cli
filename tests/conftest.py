"""Shared pytest fixtures."""

from __future__ import annotations

import json
from collections.abc import Callable
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
