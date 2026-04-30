"""Tests for `nsc commands`, the model-dump meta-command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from nsc.cli.app import app


def _bundled_schema() -> Path:
    bundled = Path(__file__).resolve().parents[2] / "nsc" / "schemas" / "bundled"
    candidates = sorted(bundled.glob("netbox-*.json"))
    assert candidates
    return candidates[-1]


def test_dumps_command_model_as_json() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app, ["commands", "--output", "json", "--schema", str(_bundled_schema())]
    )
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["info_title"].lower().startswith("netbox")
    assert "tags" in payload
    assert "dcim" in payload["tags"]
    assert "devices" in payload["tags"]["dcim"]["resources"]


def test_default_output_is_json_when_only_format_supported() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["commands", "--schema", str(_bundled_schema())])
    assert result.exit_code == 0
    json.loads(result.stdout)  # no exception


def test_unknown_schema_path_yields_nonzero_exit() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["commands", "--schema", "/no/such.json"])
    assert result.exit_code != 0
    assert "not found" in result.stderr.lower()
