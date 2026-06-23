"""Guard the architecture rule: normal CLI startup must not import Textual."""

from __future__ import annotations

import subprocess
import sys


def _import_leaves_textual_absent(module: str) -> None:
    code = (
        f"import {module}; import sys; "
        "leaked = sorted(m for m in sys.modules if m.startswith('textual')); "
        "assert not leaked, leaked"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_importing_cli_app_does_not_import_textual() -> None:
    _import_leaves_textual_absent("nsc.cli.app")


def test_importing_tui_package_does_not_import_textual() -> None:
    _import_leaves_textual_absent("nsc.tui")


def test_importing_tui_commands_does_not_import_textual() -> None:
    _import_leaves_textual_absent("nsc.cli.tui_commands")
