"""`NSC_SCHEMA` is the env-var form of `--schema` (#192)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx2
import pytest
import respx
from typer.testing import CliRunner

from nsc.cli.app import app

_NETBOX_SCHEMA = "https://nb.example/api/schema/?format=json"
_REMOTE_SCHEMA = "https://schemas.example/s.json"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NSC_HOME", str(tmp_path))
    monkeypatch.setenv("NSC_URL", "https://nb.example/")
    monkeypatch.setenv("NSC_TOKEN", "tok")
    for var in ("NSC_PROFILE", "NSC_SCHEMA", "NSC_OUTPUT", "NSC_BRANCH"):
        monkeypatch.delenv(var, raising=False)


def _widgets_schema() -> dict[str, object]:
    # `dcim widgets` exists in no bundled schema, so seeing it proves this document was used.
    return {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1.0.0"},
        "tags": [{"name": "dcim"}],
        "paths": {
            "/api/dcim/widgets/": {
                "get": {
                    "operationId": "dcim_widgets_list",
                    "tags": ["dcim"],
                    "parameters": [],
                    "responses": {"200": {"description": "ok", "content": {}}},
                }
            }
        },
        "components": {"schemas": {}},
    }


def _write_schema(tmp_path: Path) -> str:
    path = tmp_path / "widgets.json"
    path.write_text(json.dumps(_widgets_schema()), encoding="utf-8")
    return str(path)


@pytest.mark.httpx2(assert_all_called=False)
def test_nsc_schema_local_path_is_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, httpx2_mock: respx.Router
) -> None:
    httpx2_mock.get(_NETBOX_SCHEMA).mock(side_effect=httpx2.ConnectError("offline"))
    monkeypatch.setenv("NSC_SCHEMA", _write_schema(tmp_path))
    result = CliRunner().invoke(app, ["dcim", "widgets", "--help"])
    assert result.exit_code == 0, result.output
    assert "list" in result.output


def test_nsc_schema_missing_file_exits_three(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = str(tmp_path / "missing.json")
    monkeypatch.setenv("NSC_SCHEMA", missing)
    result = CliRunner().invoke(app, ["dcim", "sites", "list"])
    assert result.exit_code == 3
    assert f"Error: cannot load schema from {missing}: not found" in result.stderr


def test_nsc_schema_unreachable_url_exits_three_without_fallback(
    monkeypatch: pytest.MonkeyPatch, httpx2_mock: respx.Router
) -> None:
    httpx2_mock.get(_REMOTE_SCHEMA).mock(side_effect=httpx2.ConnectError("offline"))
    monkeypatch.setenv("NSC_SCHEMA", _REMOTE_SCHEMA)
    result = CliRunner().invoke(app, ["dcim", "sites", "list"])
    assert result.exit_code == 3
    assert f"Error: cannot load schema from {_REMOTE_SCHEMA}: request failed" in result.stderr
    assert "bundled schema" not in result.stderr


def test_schema_flag_wins_over_nsc_schema(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NSC_SCHEMA", str(tmp_path / "missing.json"))
    result = CliRunner().invoke(
        app, ["--schema", _write_schema(tmp_path), "dcim", "widgets", "--help"]
    )
    assert result.exit_code == 0, result.output


def test_empty_nsc_schema_is_unset(
    monkeypatch: pytest.MonkeyPatch, httpx2_mock: respx.Router
) -> None:
    httpx2_mock.get(_NETBOX_SCHEMA).respond(json=_widgets_schema())
    monkeypatch.setenv("NSC_SCHEMA", "")
    result = CliRunner().invoke(app, ["dcim", "widgets", "--help"])
    assert result.exit_code == 0, result.output
