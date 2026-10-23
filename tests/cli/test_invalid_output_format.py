"""An invalid `-o/--output` (or `NSC_OUTPUT`) is a usage error, never an internal crash (#179)."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest
import respx
from typer.testing import CliRunner

from nsc.cli.app import app
from nsc.config.models import OutputFormat
from nsc.output.render import select_format

_VALID = ("table", "json", "jsonl", "yaml", "csv")


@pytest.fixture(autouse=True)
def _profile(monkeypatch: pytest.MonkeyPatch, fixture_profile_yaml: Path) -> None:
    monkeypatch.setenv("NSC_HOME", str(fixture_profile_yaml))
    monkeypatch.delenv("NSC_OUTPUT", raising=False)


def _mock_schema(respx_mock: respx.Router) -> None:
    bundled = next(Path("nsc/schemas/bundled").glob("*.json*"))
    body = (
        gzip.decompress(bundled.read_bytes())
        if bundled.name.endswith(".gz")
        else bundled.read_bytes()
    )
    respx_mock.get("https://nb.example/api/schema/?format=json").respond(
        200, content=body, headers={"content-type": "application/json"}
    )


def _assert_usage_error(result: object) -> None:
    exit_code = result.exit_code  # type: ignore[attr-defined]
    combined = (result.stdout or "") + (result.stderr or "")  # type: ignore[attr-defined]
    assert exit_code == 2, (exit_code, combined)
    assert "internal" not in combined
    assert "Traceback" not in combined
    assert "bogus" in combined
    for fmt in _VALID:
        assert fmt in combined


@pytest.mark.httpx2(assert_all_called=False)
@pytest.mark.parametrize(
    "command",
    [
        ["dcim", "sites", "list", "-o", "bogus"],
        ["dcim", "sites", "list", "--output=bogus"],
        ["dcim", "sites", "get", "1", "-o", "bogus"],
        ["dcim", "sites", "create", "--name", "x", "-o", "bogus"],
        ["-o", "bogus", "dcim", "sites", "list"],
        ["ls", "sites", "-o", "bogus"],
        ["get", "sites", "1", "-o", "bogus"],
        ["search", "x", "-o", "bogus"],
        ["branch", "list", "-o", "bogus"],
    ],
)
def test_invalid_output_flag_is_usage_error(httpx2_mock: respx.Router, command: list[str]) -> None:
    _mock_schema(httpx2_mock)
    _assert_usage_error(CliRunner().invoke(app, command))


@pytest.mark.httpx2(assert_all_called=False)
def test_invalid_nsc_output_env_is_usage_error(
    httpx2_mock: respx.Router, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_schema(httpx2_mock)
    monkeypatch.setenv("NSC_OUTPUT", "bogus")
    result = CliRunner().invoke(app, ["dcim", "sites", "list"])
    _assert_usage_error(result)
    assert "NSC_OUTPUT" in (result.stdout or "") + (result.stderr or "")


@pytest.mark.httpx2(assert_all_called=False)
def test_invalid_output_does_not_fetch_schema(httpx2_mock: respx.Router) -> None:
    schema_route = httpx2_mock.get("https://nb.example/api/schema/?format=json").respond(500)
    result = CliRunner().invoke(app, ["dcim", "sites", "list", "-o", "bogus"])
    assert result.exit_code == 2
    assert not schema_route.called


@pytest.mark.httpx2(assert_all_called=False)
def test_dynamic_command_help_lists_output_choices(httpx2_mock: respx.Router) -> None:
    _mock_schema(httpx2_mock)
    result = CliRunner().invoke(app, ["dcim", "sites", "list", "--help"])
    assert result.exit_code == 0, result.stdout
    assert "jsonl" in result.stdout


def test_empty_nsc_output_env_is_treated_as_unset() -> None:
    fmt = select_format(cli_value=None, env_value="", is_tty=True, default=OutputFormat.YAML)
    assert fmt is OutputFormat.YAML
