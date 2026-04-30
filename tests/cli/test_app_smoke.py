"""Smoke tests that prove the Typer entry point is wired up."""

from __future__ import annotations

from typer.testing import CliRunner

from nsc._version import __version__
from nsc.cli.app import app


def test_version_flag_prints_version() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_no_args_shows_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, [])
    # Typer with `no_args_is_help=True` exits 0 and prints help.
    assert result.exit_code in (0, 2)
    assert "netbox-super-cli" in result.stdout
