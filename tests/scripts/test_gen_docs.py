"""Tests for the auto-generated docs reference pages (Phase 5b)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import yaml

from nsc.output.errors import ErrorType

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _import_module():
    """Import scripts/gen_docs.py without it being a package member."""
    path = REPO_ROOT / "scripts" / "gen_docs.py"
    spec = importlib.util.spec_from_file_location("gen_docs", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_render_cli_includes_top_level_heading_and_at_least_one_tag() -> None:
    g = _import_module()
    out = g.render_cli()
    assert out.startswith("# CLI reference"), out[:200]
    # The bundled NetBox 4.6.0 schema has a 'dcim' tag. If your bundled
    # manifest has a different version that doesn't include dcim, swap the
    # assertion to whichever tag IS present.
    assert "## dcim" in out or "## DCIM" in out, "expected a dcim section in cli.md"


def test_render_config_lists_pydantic_field_names() -> None:
    g = _import_module()
    out = g.render_config()
    assert out.startswith("# Configuration reference"), out[:200]
    for field_name in ("default_profile", "profiles", "defaults", "columns"):
        assert field_name in out, f"missing field {field_name!r}"


def test_render_schemas_lists_bundled_versions() -> None:
    g = _import_module()
    out = g.render_schemas()
    assert out.startswith("# Bundled schemas"), out[:200]
    manifest = yaml.safe_load(
        (REPO_ROOT / "nsc" / "schemas" / "bundled" / "manifest.yaml").read_text()
    )
    for entry in manifest["schemas"]:
        assert entry["version"] in out, f"missing version {entry['version']!r}"


def test_render_exit_codes_lists_every_error_type() -> None:
    g = _import_module()
    out = g.render_exit_codes()
    assert out.startswith("# Exit codes"), out[:200]
    for et in ErrorType:
        assert et.value in out, f"missing error type {et.value!r}"


def test_check_flag_passes_when_pages_match() -> None:
    """Running --check immediately after a non-check generation must exit 0."""
    g = _import_module()
    g.main(check=False)
    rc = g.main(check=True)
    assert rc == 0


def test_check_flag_fails_when_a_page_drifts() -> None:
    """Tampering with one generated page must make --check exit non-zero."""
    g = _import_module()
    target = REPO_ROOT / "docs" / "reference" / "exit-codes.md"
    original = target.read_text()
    try:
        target.write_text(original + "\n# DRIFT MARKER\n")
        rc = g.main(check=True)
        assert rc != 0
    finally:
        target.write_text(original)


def test_cli_invocation_writes_files() -> None:
    """`python scripts/gen_docs.py` (no --check) writes the four pages and exits 0."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "gen_docs.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    for name in ("cli.md", "config.md", "schemas.md", "exit-codes.md"):
        assert (REPO_ROOT / "docs" / "reference" / name).exists()
