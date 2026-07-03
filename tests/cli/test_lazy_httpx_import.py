"""Guard the startup-perf rule: normal CLI startup must not import httpx.

httpx is the single heaviest import in the tree (~65 ms cold). Nothing on the
`nsc --help` path needs an HTTP client, so httpx must stay lazy — pulled in only
when a request is actually made. See issue #13.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _import_leaves_httpx_absent(module: str) -> None:
    code = (
        f"import {module}; import sys; "
        "leaked = sorted(m for m in sys.modules if m == 'httpx' or m.startswith('httpx.')); "
        "assert not leaked, leaked"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_importing_cli_app_does_not_import_httpx() -> None:
    _import_leaves_httpx_absent("nsc.cli.app")


def test_help_invocation_does_not_import_httpx(tmp_path: Path) -> None:
    # Belt-and-braces over the import-only guard: an actual `--help` run against
    # an unconfigured home (the cold-start path the benchmark measures) must not
    # drag httpx in either. `-X importtime` writes every imported module to
    # stderr; assert httpx never appears. A configured profile legitimately
    # builds a NetBoxClient at bootstrap, so this isolates NSC_HOME to keep the
    # guard about help-rendering, not client construction.
    env = {**os.environ, "NSC_HOME": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-X", "importtime", "-m", "nsc", "--help"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    httpx_lines = [line for line in result.stderr.splitlines() if " httpx" in line]
    assert not httpx_lines, httpx_lines
