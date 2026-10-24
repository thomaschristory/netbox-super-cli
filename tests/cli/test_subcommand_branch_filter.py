"""A subcommand's own `--branch` query filter is not the global branch selector (#170, #180)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import respx
from typer.testing import CliRunner

from nsc.cli.app import app
from tests.branching._fixtures import branch_json, page

NB = "https://nb.example"
BRANCHES = f"{NB}/api/plugins/branching/branches/"
CHANGES = f"{NB}/api/branching/changes/"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NSC_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NSC_URL", f"{NB}/")
    monkeypatch.setenv("NSC_TOKEN", "tok")
    for var in ("NSC_PROFILE", "NSC_SCHEMA", "NSC_OUTPUT", "NSC_BRANCH"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def schema(tmp_path: Path) -> str:
    # Mirrors the Branching plugin's `changes` list (a `branch` query filter) on a
    # plain /api/<tag>/<resource>/ path, so the command name is unambiguous.
    doc = {
        "openapi": "3.0.3",
        "info": {"title": "T", "version": "1.0.0"},
        "tags": [{"name": "branching"}],
        "paths": {
            "/api/branching/changes/": {
                "get": {
                    "operationId": "branching_changes_list",
                    "tags": ["branching"],
                    "parameters": [{"name": "branch", "in": "query", "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "ok", "content": {}}},
                }
            }
        },
        "components": {"schemas": {}},
    }
    path = tmp_path / "changes.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


def _mock_lookup(router: respx.Router) -> respx.Route:
    data = branch_json()
    router.get(BRANCHES, params={"schema_id": data["name"]}).respond(200, json=page())
    return router.get(BRANCHES, params={"name": data["name"]}).respond(200, json=page(data))


def _invoke(schema: str, *args: str) -> Any:
    return CliRunner().invoke(app, ["--schema", schema, *args, "--output", "json"])


def test_subcommand_branch_is_a_query_filter_not_a_branch_switch(
    httpx2_mock: respx.Router, schema: str
) -> None:
    changes = httpx2_mock.get(CHANGES).respond(200, json=page())
    result = _invoke(schema, "branching", "changes", "list", "--branch", "my-change")
    assert result.exit_code == 0, result.output
    request = changes.calls.last.request
    assert request.url.params["branch"] == "my-change"
    assert "x-netbox-branch" not in request.headers
    assert "⎇" not in result.stderr


def test_root_branch_selects_the_branch(httpx2_mock: respx.Router, schema: str) -> None:
    lookup = _mock_lookup(httpx2_mock)
    changes = httpx2_mock.get(CHANGES).respond(200, json=page())
    result = _invoke(schema, "--branch", "my-change", "branching", "changes", "list")
    assert result.exit_code == 0, result.output
    assert lookup.called
    request = changes.calls.last.request
    assert request.headers["x-netbox-branch"] == "abcd1234"
    assert "branch" not in request.url.params
    assert "⎇ branch: my-change" in result.stderr


def test_root_branch_and_subcommand_filter_are_independent(
    httpx2_mock: respx.Router, schema: str
) -> None:
    _mock_lookup(httpx2_mock)
    changes = httpx2_mock.get(CHANGES).respond(200, json=page())
    result = _invoke(
        schema, "--branch", "my-change", "branching", "changes", "list", "--branch", "other"
    )
    assert result.exit_code == 0, result.output
    request = changes.calls.last.request
    assert request.headers["x-netbox-branch"] == "abcd1234"
    assert request.url.params["branch"] == "other"
