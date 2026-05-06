"""Tests for `nsc init` (first-run wizard)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from nsc.cli.app import app


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".nsc"
    home.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NSC_HOME", str(home))
    return home


def test_init_writes_minimal_config_on_clean_home(home: Path) -> None:
    runner = CliRunner()
    # Stdin order: profile name, URL, verify SSL, token storage choice, token literal.
    result = runner.invoke(
        app,
        ["init"],
        input="prod\nhttps://nb.example/\ny\nplaintext\nabcd1234\n",
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    body = (home / "config.yaml").read_text(encoding="utf-8")
    assert "default_profile: prod" in body
    assert "url: https://nb.example/" in body
    assert "token: abcd1234" in body


def test_init_with_env_token_storage_writes_env_tag(home: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["init"],
        input="prod\nhttps://nb.example/\ny\nenv\nNSC_PROD_TOKEN\n",
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    body = (home / "config.yaml").read_text(encoding="utf-8")
    assert "token: !env NSC_PROD_TOKEN" in body


def test_init_refuses_to_clobber_existing_config(home: Path) -> None:
    (home / "config.yaml").write_text("default_profile: existing\nprofiles: {}\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(app, ["init"])
    assert result.exit_code != 0
    combined = result.stdout + result.stderr
    assert "already exists" in combined
    assert "login --new" in combined
    # Original config left intact.
    assert (home / "config.yaml").read_text(
        encoding="utf-8"
    ) == "default_profile: existing\nprofiles: {}\n"


def test_init_refuses_to_clobber_malformed_existing_config(home: Path) -> None:
    """A pre-existing file that fails to parse is still 'present' — refuse, don't clobber."""
    (home / "config.yaml").write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 12
    combined = result.stdout + result.stderr
    assert "already exists" in combined
    assert (home / "config.yaml").read_text(encoding="utf-8") == "- not\n- a\n- mapping\n"


def test_init_treats_empty_existing_config_as_clean(home: Path) -> None:
    (home / "config.yaml").write_text("", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["init"],
        input="prod\nhttps://nb.example/\ny\nplaintext\nabcd1234\n",
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "default_profile: prod" in (home / "config.yaml").read_text(encoding="utf-8")


def test_init_with_verify_ssl_disabled_writes_false(home: Path) -> None:
    runner = CliRunner()
    # Stdin order: profile name, URL, verify SSL (no), token storage, token.
    result = runner.invoke(
        app,
        ["init"],
        input="prod\nhttps://nb.example/\nn\nplaintext\nabcd1234\n",
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    body = (home / "config.yaml").read_text(encoding="utf-8")
    assert "verify_ssl: false" in body


def test_init_with_verify_ssl_enabled_omits_field(home: Path) -> None:
    runner = CliRunner()
    # Stdin order: profile name, URL, verify SSL (yes), token storage, token.
    result = runner.invoke(
        app,
        ["init"],
        input="prod\nhttps://nb.example/\ny\nplaintext\nabcd1234\n",
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    body = (home / "config.yaml").read_text(encoding="utf-8")
    assert "verify_ssl" not in body
