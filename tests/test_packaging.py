"""Packaging-metadata guards.

Protects against importing a third-party package directly while relying on
another dependency to supply it transitively. That is exactly how `click`
broke on fresh installs (issue #81): `nsc` imports `click` directly, but it
was only ever pulled in via `typer` — and typer 0.26 vendored click as
`typer._click` and dropped its public `click` dependency, so fresh
resolutions had no `click` and `import click` crashed.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys
import tomllib
from importlib.metadata import packages_distributions

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_NSC = _REPO_ROOT / "nsc"


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def _declared_dependencies() -> set[str]:
    data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps: list[str] = data["project"]["dependencies"]
    return {_canonical(re.split(r"[<>=!~\[; ]", dep, maxsplit=1)[0]) for dep in deps}


def _top_level_imports(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def _directly_imported_modules() -> set[str]:
    names: set[str] = set()
    for path in _NSC.rglob("*.py"):
        names |= _top_level_imports(ast.parse(path.read_text(encoding="utf-8")))
    return names


def test_click_is_a_declared_dependency() -> None:
    # The concrete regression guard for issue #81: nsc imports click directly.
    assert "click" in _directly_imported_modules()
    assert _canonical("click") in _declared_dependencies()


def test_every_direct_third_party_import_is_declared() -> None:
    # Generalizes the guard: any top-level third-party module imported anywhere
    # in nsc/ must resolve to a declared dependency — never a transitive freebie.
    declared = _declared_dependencies()
    dist_map = packages_distributions()
    undeclared: dict[str, set[str]] = {}
    for module in _directly_imported_modules():
        if module == "nsc" or module in sys.stdlib_module_names:
            continue
        dists = dist_map.get(module)
        if dists is None:
            continue  # not an installed distribution (e.g. a namespace shim)
        if not any(_canonical(dist) in declared for dist in dists):
            undeclared[module] = set(dists)
    assert not undeclared, f"third-party imports missing from dependencies: {undeclared}"
