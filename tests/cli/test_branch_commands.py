"""`nsc branch …` commands, driven through the real Typer app."""

from __future__ import annotations

import gzip
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


@pytest.fixture(autouse=True)
def _home(monkeypatch: pytest.MonkeyPatch, fixture_profile_yaml: Path) -> Path:
    monkeypatch.setenv("NSC_HOME", str(fixture_profile_yaml))
    for var in ("NSC_BRANCH", "NSC_URL", "NSC_TOKEN", "NSC_PROFILE", "NSC_OUTPUT"):
        monkeypatch.delenv(var, raising=False)
    return fixture_profile_yaml


def _mock_schema(router: respx.Router) -> None:
    bundled = next(Path("nsc/schemas/bundled").glob("*.json*"))
    body = gzip.decompress(bundled.read_bytes())
    router.get(f"{NB}/api/schema/?format=json").respond(
        200, content=body, headers={"content-type": "application/json"}
    )


def _mock_lookup(router: respx.Router, **over: Any) -> None:
    data = branch_json(**over)
    router.get(BRANCHES, params={"name": data["name"]}).respond(200, json=page(data))
    router.get(BRANCHES, params={"schema_id": data["name"]}).respond(200, json=page())


def _set_profile_branch(home: Path, name: str) -> None:
    cfg = home / "config.yaml"
    text = cfg.read_text().replace("    token: t0ken\n", f"    token: t0ken\n    branch: {name}\n")
    cfg.write_text(text)


def _invoke(*args: str, env: dict[str, str] | None = None) -> Any:
    return CliRunner().invoke(app, list(args), env=env)


def test_list_marks_active(httpx2_mock: respx.Router, _home: Path) -> None:
    _mock_schema(httpx2_mock)
    _set_profile_branch(_home, "my-change")
    httpx2_mock.get(BRANCHES).respond(
        200, json=page(branch_json(), branch_json(id=4, name="other", schema_id="zzzz9999"))
    )
    result = _invoke("branch", "list", "--output", "json")
    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)
    assert [(r["name"], r["active"]) for r in rows] == [("my-change", True), ("other", False)]
    assert "⎇ branch: my-change" in result.stderr


def test_current_reports_source_without_network(httpx2_mock: respx.Router) -> None:
    _mock_schema(httpx2_mock)
    result = _invoke("--branch", "feat-x", "branch", "current", "--output", "json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"branch": "feat-x", "source": "flag"}


def test_current_main_when_none(httpx2_mock: respx.Router) -> None:
    _mock_schema(httpx2_mock)
    result = _invoke("branch", "current", "--output", "table")
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "main"


def test_create_waits_then_use_persists_profile_branch(
    httpx2_mock: respx.Router, _home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("nsc.cli.branch_commands.time.sleep", lambda s: None)
    _mock_schema(httpx2_mock)
    httpx2_mock.post(BRANCHES).respond(201, json=branch_json(status={"value": "new"}))
    httpx2_mock.get(f"{BRANCHES}3/").mock(
        side_effect=[
            respx.MockResponse(200, json=branch_json(status={"value": "provisioning"})),
            respx.MockResponse(200, json=branch_json()),
        ]
    )
    result = _invoke("branch", "create", "my-change", "--use", "--output", "json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"] == "ready"
    assert "branch: my-change" in (_home / "config.yaml").read_text()


def test_use_validates_ready(httpx2_mock: respx.Router, _home: Path) -> None:
    _mock_schema(httpx2_mock)
    _mock_lookup(httpx2_mock, status={"value": "merged"})
    before = (_home / "config.yaml").read_text()
    result = _invoke("branch", "use", "my-change", "--output", "json")
    assert result.exit_code == 12, result.output
    assert json.loads(result.stdout)["details"]["status"] == "merged"
    assert (_home / "config.yaml").read_text() == before


def test_use_persists_and_preserves_comments(httpx2_mock: respx.Router, _home: Path) -> None:
    _mock_schema(httpx2_mock)
    cfg = _home / "config.yaml"
    cfg.write_text("# keep me\n" + cfg.read_text())
    _mock_lookup(httpx2_mock)
    result = _invoke("branch", "use", "my-change")
    assert result.exit_code == 0, result.output
    text = cfg.read_text()
    assert text.startswith("# keep me\n")
    assert "branch: my-change" in text


@pytest.mark.httpx2(assert_all_called=False)
def test_use_main_unsets_without_network(httpx2_mock: respx.Router, _home: Path) -> None:
    _mock_schema(httpx2_mock)
    _set_profile_branch(_home, "my-change")
    lookup = httpx2_mock.get(BRANCHES).respond(200, json=page())
    result = _invoke("branch", "use", "--main")
    assert result.exit_code == 0, result.output
    assert "branch:" not in (_home / "config.yaml").read_text()
    assert not lookup.called


@pytest.mark.httpx2(assert_all_called=False)
def test_use_adhoc_profile_rejected(httpx2_mock: respx.Router, _home: Path) -> None:
    (_home / "config.yaml").write_text("defaults:\n  output: table\n")
    _mock_schema(httpx2_mock)
    _mock_lookup(httpx2_mock)
    result = _invoke(
        "branch",
        "use",
        "my-change",
        "--output",
        "json",
        env={"NSC_URL": NB, "NSC_TOKEN": "tok"},
    )
    assert result.exit_code == 12, result.output
    assert "NSC_BRANCH" in json.loads(result.stdout)["error"]


def test_diff_table_lists_changed_fields(httpx2_mock: respx.Router) -> None:
    _mock_schema(httpx2_mock)
    _mock_lookup(httpx2_mock)
    httpx2_mock.get(f"{NB}/api/plugins/branching/changes/").respond(
        200,
        json=page(
            {
                "id": 1,
                "object_type": "dcim.site",
                "object_repr": "London",
                "action": {"value": "update", "label": "Updated"},
                "original": {"name": "Lon", "status": "planned", "slug": "lon"},
                "modified": {"name": "London", "status": "active", "slug": "lon"},
            }
        ),
    )
    result = _invoke("branch", "diff", "my-change", "--output", "csv")
    assert result.exit_code == 0, result.output
    lines = result.stdout.strip().splitlines()
    assert lines[0] == "action,object_type,object,fields"
    assert lines[1] == 'update,dcim.site,London,"name, status"'


def test_branch_commands_never_send_branch_header(httpx2_mock: respx.Router, _home: Path) -> None:
    _mock_schema(httpx2_mock)
    _set_profile_branch(_home, "my-change")
    route = httpx2_mock.get(BRANCHES).respond(200, json=page(branch_json()))
    result = _invoke("branch", "list")
    assert result.exit_code == 0, result.output
    assert "x-netbox-branch" not in route.calls.last.request.headers


def test_show_defaults_to_active(httpx2_mock: respx.Router) -> None:
    _mock_schema(httpx2_mock)
    _mock_lookup(httpx2_mock)
    result = _invoke("--branch", "my-change", "branch", "show", "--output", "json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["schema_id"] == "abcd1234"


def test_show_without_name_or_active_is_input_error(httpx2_mock: respx.Router) -> None:
    _mock_schema(httpx2_mock)
    result = _invoke("branch", "show", "--output", "json")
    assert result.exit_code == 4, result.output
    assert json.loads(result.stdout)["type"] == "input_error"


@pytest.mark.httpx2(assert_all_called=False)
@pytest.mark.parametrize(
    "command",
    [["dcim", "sites", "list"], ["ls", "sites"], ["dcim", "sites", "get", "1"]],
)
def test_sticky_merged_branch_fails_loudly(
    httpx2_mock: respx.Router, _home: Path, command: list[str]
) -> None:
    _mock_schema(httpx2_mock)
    _set_profile_branch(_home, "my-change")
    _mock_lookup(httpx2_mock, status={"value": "merged"})
    sites = httpx2_mock.get(url__startswith=f"{NB}/api/dcim/sites/").respond(200, json=page())
    result = _invoke(*command, "--output", "json")
    assert result.exit_code == 12, (result.exit_code, result.output, result.exception)
    env = json.loads(result.stdout)
    assert env["details"] == {"branch": "my-change", "status": "merged"}
    assert "nsc branch use --main" in env["error"]
    assert not sites.called


@pytest.mark.httpx2(assert_all_called=False)
def test_use_main_works_when_active_branch_is_merged(
    httpx2_mock: respx.Router, _home: Path
) -> None:
    _mock_schema(httpx2_mock)
    _set_profile_branch(_home, "my-change")
    _mock_lookup(httpx2_mock, status={"value": "merged"})
    result = _invoke("branch", "use", "--main")
    assert result.exit_code == 0, result.output
    assert "branch:" not in (_home / "config.yaml").read_text()
