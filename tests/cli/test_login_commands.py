"""Tests for `nsc login` (bare / --new / --rotate)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import respx
from httpx import Response
from typer.testing import CliRunner

from nsc.cli.app import app


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".nsc"
    home.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NSC_HOME", str(home))
    return home


def _seed(home: Path, body: str) -> None:
    (home / "config.yaml").write_text(body, encoding="utf-8")


def _good_status() -> None:
    respx.get("https://nb.example/api/status/").mock(
        return_value=Response(200, json={"netbox-version": "4.5.9"})
    )
    respx.get("https://nb.example/api/users/tokens/").mock(
        return_value=Response(200, json={"results": [{"user": {"username": "alice"}}]})
    )


@respx.mock
def test_login_bare_verifies_default_profile(home: Path) -> None:
    _seed(
        home,
        "default_profile: prod\n"
        "profiles:\n"
        "  prod:\n"
        "    url: https://nb.example/\n"
        "    token: T123\n",
    )
    _good_status()
    runner = CliRunner()
    result = runner.invoke(app, ["login"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "alice" in result.stdout
    assert "4.5.9" in result.stdout


@respx.mock
def test_login_bare_surfaces_auth_envelope_on_bad_token(home: Path) -> None:
    _seed(
        home,
        "default_profile: prod\nprofiles:\n  prod:\n    url: https://nb.example/\n    token: BAD\n",
    )
    respx.get("https://nb.example/api/status/").mock(
        return_value=Response(200, json={"netbox-version": "4.5.9"})
    )
    respx.get("https://nb.example/api/users/tokens/").mock(return_value=Response(403, json={}))
    runner = CliRunner()
    result = runner.invoke(app, ["login"])
    assert result.exit_code == 8  # ErrorType.AUTH
    combined = result.stdout + result.stderr
    assert "auth" in combined.lower() or "rejected" in combined.lower()


@respx.mock
def test_login_new_creates_and_verifies(home: Path) -> None:
    _good_status()
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "login",
            "--new",
            "--profile",
            "prod",
            "--url",
            "https://nb.example/",
            "--store",
            "plaintext",
        ],
        input="T123\nn\n",
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    body = (home / "config.yaml").read_text(encoding="utf-8")
    assert "prod:" in body
    assert "url: https://nb.example/" in body
    assert "token: T123" in body
    # First profile becomes the default.
    assert "default_profile: prod" in body


def test_login_new_refuses_to_clobber_existing_profile(home: Path) -> None:
    _seed(
        home,
        "default_profile: prod\nprofiles:\n  prod:\n    url: https://x/\n    token: t\n",
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["login", "--new", "--profile", "prod", "--url", "https://nb.example/"],
        input="T123\n",
    )
    assert result.exit_code != 0
    combined = result.stdout + result.stderr
    assert "exists" in combined
    assert "--rotate" in combined


@respx.mock
def test_login_rotate_replaces_token_after_verifying_new_one(home: Path) -> None:
    _seed(
        home,
        "default_profile: prod\nprofiles:\n  prod:\n    url: https://nb.example/\n    token: OLD\n",
    )
    _good_status()
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["login", "--rotate", "--profile", "prod"],
        input="NEWTOKEN\n",
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    body = (home / "config.yaml").read_text(encoding="utf-8")
    assert "token: NEWTOKEN" in body
    assert "OLD" not in body


@respx.mock
def test_login_new_with_env_storage_writes_env_tag(home: Path) -> None:
    _good_status()
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "login",
            "--new",
            "--profile",
            "prod",
            "--url",
            "https://nb.example/",
            "--store",
            "env",
            "--env-var",
            "NSC_PROD_TOKEN",
        ],
        input="T123\nn\n",  # token is still prompted; only the storage form differs
        env={"NSC_PROD_TOKEN": "T123"},
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    body = (home / "config.yaml").read_text(encoding="utf-8")
    assert "!env" in body
    assert "NSC_PROD_TOKEN" in body


# ---------------------------------------------------------------------------
# --fetch-schema flag and interactive schema-fetch prompt
# ---------------------------------------------------------------------------


def _patch_resolve(monkeypatch: pytest.MonkeyPatch, calls: list[Any]) -> None:
    def _mock(**_: Any) -> Any:
        calls.append(True)

    monkeypatch.setattr("nsc.cli.login_commands.resolve_command_model", _mock)


@respx.mock
def test_login_new_without_flag_prompts_yes_fetches(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _good_status()
    calls: list[Any] = []
    _patch_resolve(monkeypatch, calls)
    result = CliRunner().invoke(
        app,
        ["login", "--new", "--profile", "prod", "--url", "https://nb.example/"],
        input="T123\ny\n",
    )
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert "Fetching schema" in result.output


@respx.mock
def test_login_new_without_flag_default_yes_fetches(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _good_status()
    calls: list[Any] = []
    _patch_resolve(monkeypatch, calls)
    result = CliRunner().invoke(
        app,
        ["login", "--new", "--profile", "prod", "--url", "https://nb.example/"],
        input="T123\n\n",
    )
    assert result.exit_code == 0, result.output
    assert len(calls) == 1


@respx.mock
def test_login_new_without_flag_prompts_no_skips(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _good_status()
    calls: list[Any] = []
    _patch_resolve(monkeypatch, calls)
    result = CliRunner().invoke(
        app,
        ["login", "--new", "--profile", "prod", "--url", "https://nb.example/"],
        input="T123\nn\n",
    )
    assert result.exit_code == 0, result.output
    assert len(calls) == 0


@respx.mock
def test_login_new_fetch_schema_flag_skips_prompt(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _good_status()
    calls: list[Any] = []
    _patch_resolve(monkeypatch, calls)
    result = CliRunner().invoke(
        app,
        ["login", "--new", "--profile", "prod", "--url", "https://nb.example/", "--fetch-schema"],
        input="T123\n",
    )
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert "Fetching schema" in result.output


@respx.mock
def test_login_verify_fetch_schema_flag_fetches(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(
        home,
        "default_profile: prod\n"
        "profiles:\n"
        "  prod:\n"
        "    url: https://nb.example/\n"
        "    token: T123\n",
    )
    _good_status()
    calls: list[Any] = []
    _patch_resolve(monkeypatch, calls)
    result = CliRunner().invoke(app, ["login", "--fetch-schema"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert "Fetching schema" in result.output


@respx.mock
def test_login_fetch_schema_failure_warns_and_exits_zero(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(
        home,
        "default_profile: prod\n"
        "profiles:\n"
        "  prod:\n"
        "    url: https://nb.example/\n"
        "    token: T123\n",
    )
    _good_status()

    def _fail(**_: Any) -> Any:
        raise RuntimeError("network down")

    monkeypatch.setattr("nsc.cli.login_commands.resolve_command_model", _fail)
    result = CliRunner().invoke(app, ["login", "--fetch-schema"])
    assert result.exit_code == 0, result.output
    assert "Warning" in result.output
