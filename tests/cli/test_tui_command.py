from __future__ import annotations

from typer.testing import CliRunner

from nsc.cli.app import app


def test_tui_help_lists_resource_argument() -> None:
    result = CliRunner().invoke(app, ["tui", "--help"])
    assert result.exit_code == 0
    assert "resource" in result.output.lower()
