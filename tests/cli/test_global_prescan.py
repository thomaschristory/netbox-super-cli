"""The global-flag prescan must not read another option's value as a global flag (#182)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nsc.cli import app as app_module
from nsc.cli.app import _extract_global_overrides

_BUNDLED = str(
    Path(__file__).resolve().parents[2] / "nsc" / "schemas" / "bundled" / "netbox-4.6.0.json.gz"
)


@pytest.mark.parametrize(
    "args",
    [
        ["dcim", "devices", "create", "--name", "-o", "--dry-run"],
        ["dcim", "devices", "create", "--name", "--output", "--dry-run"],
        ["dcim", "devices", "create", "--name", "-o"],
    ],
)
def test_output_flag_used_as_option_value_is_not_global(args: list[str]) -> None:
    assert _extract_global_overrides(args).output is None


def test_real_output_flag_after_option_value_is_read() -> None:
    args = ["dcim", "devices", "create", "--name", "-o", "-o", "json"]
    assert _extract_global_overrides(args).output == "json"


def test_output_after_subcommand_still_read() -> None:
    assert _extract_global_overrides(["dcim", "devices", "list", "-o", "json"]).output == "json"


def test_invalid_output_value_after_subcommand_still_read_for_validation() -> None:
    assert _extract_global_overrides(["dcim", "devices", "list", "-o", "yaml2"]).output == "yaml2"


def test_root_flags_before_subcommand_unchanged() -> None:
    overrides = _extract_global_overrides(["--url", "https://nb.example/", "-o", "json", "ls"])
    assert overrides.url == "https://nb.example/"
    assert overrides.output == "json"


def test_flag_after_option_value_still_scanned() -> None:
    args = ["dcim", "devices", "create", "--name", "-o", "--refresh-schema"]
    overrides = _extract_global_overrides(args)
    assert overrides.output is None
    assert overrides.refresh_schema is True


def test_option_value_dash_o_reaches_click_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NSC_HOME", str(tmp_path))
    for var in ("NSC_PROFILE", "NSC_SCHEMA", "NSC_OUTPUT", "NSC_BRANCH"):
        monkeypatch.delenv(var, raising=False)
    args = ["--url", "https://nb.example/", "--token", "tok", "--schema", _BUNDLED]
    args += ["dcim", "sites", "create", "--columns", "-o", "--field", "name=x", "--field", "slug=x"]
    result = CliRunner().invoke(app_module.app, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["requests"][0]["body"] == {"name": "x", "slug": "x"}
