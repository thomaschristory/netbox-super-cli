"""Guard the startup-perf rule: `keyring` loads only when a `!keyring` token is resolved."""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "module",
    ["nsc.cli.app", "nsc.config.loader", "nsc.config.writer", "nsc.auth.keyring_store"],
)
def test_import_does_not_load_keyring(module: str) -> None:
    code = (
        f"import {module}; import sys; "
        "leaked = sorted(m for m in sys.modules if m == 'keyring' or m.startswith('keyring.')); "
        "assert not leaked, leaked"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
