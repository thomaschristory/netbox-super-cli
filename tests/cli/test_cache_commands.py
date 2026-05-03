"""Typer-level tests for `nsc cache prune` (Phase 5a)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nsc.cli.app import app


def _seed_cache(home: Path, profile: str, schema_hash: str) -> Path:
    cache_root = home / "cache"
    profile_dir = cache_root / profile
    profile_dir.mkdir(parents=True, exist_ok=True)
    target = profile_dir / f"{schema_hash}.json"
    target.write_text("{}")
    return target


def _set_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    """Point default_paths() at a temporary ~/.nsc/."""
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NSC_HOME", str(home))


def test_cache_prune_dry_run_lists_orphan_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "nsc-home"
    _set_home(monkeypatch, home)
    _seed_cache(home, "removed", "a" * 64)
    # Empty config file → no profiles → 'removed' is orphan.
    (home / "config.yaml").write_text("default_profile: null\nprofiles: {}\n")

    runner = CliRunner()
    result = runner.invoke(app, ["cache", "prune"])

    assert result.exit_code == 0, result.output
    assert "removed" in result.output
    # Dry-run did NOT delete.
    assert (home / "cache" / "removed").exists()


def test_cache_prune_apply_deletes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "nsc-home"
    _set_home(monkeypatch, home)
    _seed_cache(home, "removed", "a" * 64)
    (home / "config.yaml").write_text("default_profile: null\nprofiles: {}\n")

    runner = CliRunner()
    result = runner.invoke(app, ["cache", "prune", "--apply"])

    assert result.exit_code == 0, result.output
    assert not (home / "cache" / "removed").exists()


def test_cache_prune_json_output_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "nsc-home"
    _set_home(monkeypatch, home)
    _seed_cache(home, "removed", "a" * 64)
    (home / "config.yaml").write_text("default_profile: null\nprofiles: {}\n")

    runner = CliRunner()
    result = runner.invoke(app, ["cache", "prune", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["mode"] == "dry-run"
    assert payload["plan"]["orphan_profile_dirs"]
    assert "would_free_bytes" in payload


def test_cache_prune_json_output_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "nsc-home"
    _set_home(monkeypatch, home)
    _seed_cache(home, "removed", "a" * 64)
    (home / "config.yaml").write_text("default_profile: null\nprofiles: {}\n")

    runner = CliRunner()
    result = runner.invoke(app, ["cache", "prune", "--apply", "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["mode"] == "apply"
    assert payload["result"]["deleted_dirs"] == 1
    assert payload["result"]["freed_bytes"] >= 0


def test_cache_prune_works_with_missing_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cache prune is self-healing — it must run without ~/.nsc/config.yaml."""
    home = tmp_path / "nsc-home"
    _set_home(monkeypatch, home)
    _seed_cache(home, "stranded", "a" * 64)
    # No config.yaml at all.

    runner = CliRunner()
    result = runner.invoke(app, ["cache", "prune"])

    assert result.exit_code == 0, result.output
    assert "stranded" in result.output


def test_cache_prune_skips_type_b_when_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live-hash fetcher failure must not abort the whole prune."""
    home = tmp_path / "nsc-home"
    _set_home(monkeypatch, home)
    _seed_cache(home, "prod", "a" * 64)
    (home / "config.yaml").write_text(
        "default_profile: prod\n"
        "profiles:\n"
        "  prod:\n"
        "    name: prod\n"
        "    url: https://offline.example.invalid\n"
        "    token: xxx\n"
    )

    runner = CliRunner()
    # The fetcher will fail because the URL is unresolvable; type B is silently
    # skipped. With no orphans either, the result is "nothing to do" and exit 0.
    result = runner.invoke(app, ["cache", "prune"])

    assert result.exit_code == 0, result.output
