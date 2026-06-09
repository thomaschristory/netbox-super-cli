"""Packaging-metadata guards.

Protects against importing a third-party package directly while relying on
another dependency to supply it transitively. That is exactly how `click`
broke on fresh installs (issue #81): `nsc` imports `click` directly, but it
was only ever pulled in via `typer` — and typer 0.26 dropped its transitive
`click`, so fresh resolutions had no `click` and `import click` crashed.
"""

from __future__ import annotations

import pathlib
import re
import tomllib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _declared_dependencies() -> set[str]:
    data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps: list[str] = data["project"]["dependencies"]
    return {re.split(r"[<>=!~\[; ]", dep, maxsplit=1)[0].strip().lower() for dep in deps}


def _imports_click() -> bool:
    pattern = re.compile(r"^\s*(?:import click\b|from click\b)", re.MULTILINE)
    return any(
        pattern.search(path.read_text(encoding="utf-8"))
        for path in (_REPO_ROOT / "nsc").rglob("*.py")
    )


def test_directly_imported_click_is_a_declared_dependency() -> None:
    assert _imports_click(), "expected nsc to import click directly"
    assert "click" in _declared_dependencies()
