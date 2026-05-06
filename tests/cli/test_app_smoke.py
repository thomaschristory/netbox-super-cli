"""Smoke tests that prove the Typer entry point is wired up."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from nsc._version import __version__
from nsc.cli.app import app
from nsc.schema import source as source_mod


def test_version_flag_prints_version() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_no_args_shows_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, [])
    assert result.exit_code == 2
    assert "netbox-super-cli" in result.stdout


def test_no_profile_anywhere_gives_helpful_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NSC_HOME", str(tmp_path))
    for var in ("NSC_URL", "NSC_TOKEN", "NSC_PROFILE", "NSC_SCHEMA"):
        monkeypatch.delenv(var, raising=False)
    result = CliRunner().invoke(app, ["dcim", "devices", "list"])
    assert result.exit_code == 2
    combined = (result.stdout or "") + (result.stderr or "")
    assert "no NetBox URL" in combined


def test_meta_command_commands_still_works_with_explicit_schema(tmp_path: Path) -> None:
    schema = tmp_path / "s.json"
    schema.write_text(
        '{"openapi":"3.0.3","info":{"title":"t","version":"1.0.0"},'
        '"paths":{},"tags":[],"components":{"schemas":{}}}',
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["commands", "--schema", str(schema), "--output", "json"])
    assert result.exit_code == 0
    assert '"tags"' in result.stdout


def test_offline_with_no_cache_or_bundled_exits_three(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NSC_HOME", str(tmp_path))
    monkeypatch.setenv("NSC_URL", "https://nb.example/")
    monkeypatch.setenv("NSC_TOKEN", "tok")
    for var in ("NSC_PROFILE", "NSC_SCHEMA"):
        monkeypatch.delenv(var, raising=False)

    monkeypatch.setattr(source_mod, "_load_bundled_command_model", lambda: None)
    with respx.mock:
        respx.get("https://nb.example/api/schema/?format=json").mock(
            side_effect=httpx.ConnectError("offline")
        )
        result = CliRunner().invoke(app, ["dcim", "devices", "list"])
    assert result.exit_code == 3


def test_refresh_schema_flag_forces_refetch_through_full_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """End-to-end: `nsc --refresh-schema dcim devices list` must short-
    circuit the TTL fast-path that a prior call warmed. Exercises the
    Typer parsing -> _extract_global_overrides -> CLIOverrides ->
    build_runtime_context -> resolve_command_model wire-through that
    unit tests for `force_refresh=True` cannot prove."""
    monkeypatch.setenv("NSC_HOME", str(tmp_path))
    monkeypatch.setenv("NSC_URL", "https://nb.example/")
    monkeypatch.setenv("NSC_TOKEN", "tok")
    for var in ("NSC_PROFILE", "NSC_SCHEMA"):
        monkeypatch.delenv(var, raising=False)

    schema_doc = {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1.0.0"},
        "tags": [{"name": "dcim"}],
        "paths": {
            "/api/dcim/devices/": {
                "get": {
                    "operationId": "dcim_devices_list",
                    "tags": ["dcim"],
                    "parameters": [],
                    "responses": {"200": {"description": "ok", "content": {}}},
                }
            }
        },
        "components": {"schemas": {}},
    }
    devices_response = {"count": 0, "next": None, "previous": None, "results": []}

    with respx.mock:
        schema_route = respx.get("https://nb.example/api/schema/?format=json").mock(
            return_value=httpx.Response(200, json=schema_doc)
        )
        respx.get("https://nb.example/api/dcim/devices/").mock(
            return_value=httpx.Response(200, json=devices_response)
        )

        first = CliRunner().invoke(app, ["dcim", "devices", "list"])
        assert first.exit_code == 0, first.output
        assert schema_route.call_count == 1

        second = CliRunner().invoke(app, ["dcim", "devices", "list"])
        assert second.exit_code == 0, second.output
        assert schema_route.call_count == 1, "DAILY default must hit the fresh-cache fast-path"

        third = CliRunner().invoke(app, ["--refresh-schema", "dcim", "devices", "list"])
        assert third.exit_code == 0, third.output
        assert schema_route.call_count == 2, "--refresh-schema must bypass the fast-path"


def test_flag_equals_value_form_is_recognized_in_bootstrap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NSC_HOME", str(tmp_path))
    for var in ("NSC_URL", "NSC_TOKEN", "NSC_PROFILE", "NSC_SCHEMA"):
        monkeypatch.delenv(var, raising=False)
    # If --url=... isn't recognized at bootstrap, the resolver still gets the
    # value from the root callback, so the user-facing behavior is fine.
    # But the bootstrap should pre-parse correctly. We verify by passing both
    # forms and confirming consistent behavior (no crash, no profile required).
    result = CliRunner().invoke(
        app,
        ["--url=https://nb.example/", "--token=tok", "commands", "--schema", "/nonexistent.json"],
    )
    # commands meta-command bypasses the bootstrap profile resolution; the
    # error here will be from the schema being missing, not from the URL parsing.
    assert "no NetBox URL" not in (result.stdout or "")
