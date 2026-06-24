"""Guard the pure bulk path stays Textual-free.

`selection.py` and `bulk.py` are the framework-free core that the bulk edit
flow replays against. Importing either — including their transitive imports —
must never pull Textual into ``sys.modules``, and their source must not name
Textual at all. This is a stronger guard than a single-module source scan: it
catches accidental coupling introduced through a transitively imported helper.
"""

from __future__ import annotations

import importlib
import inspect
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


@pytest.mark.parametrize("module", ["nsc.tui.selection", "nsc.tui.bulk"])
def test_importing_bulk_path_does_not_import_textual(module: str) -> None:
    _import_leaves_textual_absent(module)


@pytest.mark.parametrize("module", ["nsc.tui.selection", "nsc.tui.bulk"])
def test_bulk_path_source_names_no_textual(module: str) -> None:
    source = inspect.getsource(importlib.import_module(module))
    assert "import textual" not in source
    assert "from textual" not in source
