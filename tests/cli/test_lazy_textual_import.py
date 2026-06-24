"""Guard the architecture rule: normal CLI startup must not import Textual."""

from __future__ import annotations

import subprocess
import sys

import pytest


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


_PURE_TUI_MODULES = (
    "keymap",
    "relations",
    "catalog",
    "view",
    "filters",
    "columns",
    "forms",
    "fk",
    "search",
    "bulk",
    "selection",
    "nav",
)


@pytest.mark.parametrize("module", _PURE_TUI_MODULES)
def test_pure_tui_module_imports_no_textual(module: str) -> None:
    # The pure logic layer must stay framework-free: importing it eagerly must
    # never pull Textual into sys.modules, or the no-Textual-on-CLI-startup
    # invariant could regress through a future eager import.
    _import_leaves_textual_absent(f"nsc.tui.{module}")
