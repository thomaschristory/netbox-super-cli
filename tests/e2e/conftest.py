"""Shared fixtures, gating, and CLI subprocess helper for the e2e suite.

Gating: the entire e2e module is skipped unless NSC_E2E=1 is set in the
environment. CI sets it; the default `just test` invocation does not, so a
developer who runs `pytest` without spinning up the docker stack will see the
e2e tests skipped rather than failing to connect.

Subprocess pattern (spec §8.3): every CLI invocation in this suite goes through
``run_nsc(*args, env=None, input=None, timeout=60)``. That helper spawns
``python -m nsc ...`` exactly the way an end user would, captures stdout / stderr
/ exit-code, and returns them. This is the contract surface — do not switch to
``typer.testing.CliRunner`` under any circumstances; it bypasses the entry
point and the whole point of e2e is to exercise the real one.

NetBox state: the stack is reused across the session. Each test that creates
records uses the ``clean_tags`` fixture to wipe ``extras/tags/`` first.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest


@dataclass(frozen=True)
class CompletedNsc:
    """Result of an out-of-process ``nsc`` invocation."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    def stdout_json(self) -> object:
        """Parse stdout as JSON; convenience for ``--output json`` invocations."""
        return json.loads(self.stdout)


_DEFAULT_TOKEN = "0123456789abcdef0123456789abcdef01234567"
_DEFAULT_URL = "http://127.0.0.1:8080"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip the entire e2e suite unless NSC_E2E=1 is explicitly set."""
    if os.environ.get("NSC_E2E") == "1":
        return
    skip = pytest.mark.skip(reason="set NSC_E2E=1 (and start tests/e2e/docker-compose.yml) to run")
    for item in items:
        item.add_marker(skip)


@pytest.fixture(scope="session")
def nsc_url() -> str:
    return os.environ.get("NSC_URL", _DEFAULT_URL)


@pytest.fixture(scope="session")
def nsc_token() -> str:
    return os.environ.get("NSC_TOKEN", _DEFAULT_TOKEN)


@pytest.fixture
def tmp_nsc_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test ``$NSC_HOME`` so each test gets a fresh audit log and last-request file."""
    home = tmp_path / "nsc-home"
    home.mkdir()
    monkeypatch.setenv("NSC_HOME", str(home))
    return home


@pytest.fixture
def run_nsc(
    nsc_url: str,
    nsc_token: str,
    tmp_nsc_home: Path,
) -> Callable[..., CompletedNsc]:
    """Invoke ``python -m nsc`` as a subprocess and return ``CompletedNsc``.

    Default env carries ``NSC_URL`` / ``NSC_TOKEN`` from the session fixtures and
    ``NSC_HOME`` from ``tmp_nsc_home``. Per-call ``env`` kwargs override; passing
    ``env={"NSC_TOKEN": "..."}`` substitutes that single key without dropping the
    others.
    """

    def _run(
        *args: str,
        env: dict[str, str] | None = None,
        input: str | None = None,
        timeout: float = 60.0,
    ) -> CompletedNsc:
        merged_env = {
            **os.environ,
            "NSC_URL": nsc_url,
            "NSC_TOKEN": nsc_token,
            "NSC_HOME": str(tmp_nsc_home),
        }
        if env:
            merged_env.update(env)
        proc = subprocess.run(
            [sys.executable, "-m", "nsc", *args],
            capture_output=True,
            text=True,
            env=merged_env,
            input=input,
            timeout=timeout,
            check=False,
        )
        return CompletedNsc(
            args=tuple(args),
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    return _run


@pytest.fixture
def netbox_client(nsc_url: str, nsc_token: str) -> Iterator[httpx.Client]:
    """Direct httpx client for fixture bootstrap / state assertions.

    Tests use ``run_nsc`` to exercise the CLI; this client is for the test
    *infrastructure* — wiping state between tests, asserting "is the record
    actually in NetBox now", etc. Do not blur the distinction.
    """
    headers = {
        "Authorization": f"Token {nsc_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    with httpx.Client(base_url=nsc_url, headers=headers, timeout=30.0) as client:
        yield client


@pytest.fixture
def clean_tags(netbox_client: httpx.Client) -> Iterator[None]:
    """Delete every tag in NetBox before and after the test."""

    def _wipe() -> None:
        # paginate defensively in case a previous test leaked many tags
        while True:
            r = netbox_client.get("/api/extras/tags/", params={"limit": 200})
            r.raise_for_status()
            results = r.json().get("results", [])
            if not results:
                return
            ids = [{"id": tag["id"]} for tag in results]
            d = netbox_client.request("DELETE", "/api/extras/tags/", json=ids)
            # 204 (bulk delete) or 200 (older versions) both acceptable
            assert d.status_code in (200, 204), d.text

    _wipe()
    yield
    _wipe()
