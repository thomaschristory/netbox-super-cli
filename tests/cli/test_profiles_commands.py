"""Tests for `nsc profiles {list,add,remove,rename,set-default}`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx
from httpx import Response
from typer.testing import CliRunner

from nsc.cli.app import app


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".nsc"
    home.mkdir()
    (home / "cache").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NSC_HOME", str(home))
    return home


def _seed(home: Path, body: str) -> None:
    (home / "config.yaml").write_text(body, encoding="utf-8")


def _good_status() -> None:
    respx.get("https://nb.example/api/status/").mock(
        return_value=Response(200, json={"netbox-version": "4.5.9"})
    )
    respx.get("https://nb.example/api/users/me/").mock(
        return_value=Response(200, json={"username": "alice"})
    )


def test_profiles_list_marks_default(home: Path) -> None:
    _seed(
        home,
        "default_profile: prod\n"
        "profiles:\n"
        "  prod: {url: https://nb1/, token: t1}\n"
        "  lab: {url: https://nb2/, token: t2}\n",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["profiles", "list"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "prod" in result.stdout
    assert "lab" in result.stdout
    assert "*" in result.stdout or "(default)" in result.stdout


def test_profiles_list_rejects_unknown_output_format(home: Path) -> None:
    """`--output yaml` (or any non-{table,json}) must error, not silently fall through."""
    _seed(
        home,
        "default_profile: prod\nprofiles:\n  prod: {url: https://nb1/, token: t1}\n",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["profiles", "list", "--output", "yaml"])
    assert result.exit_code != 0


def test_profiles_list_json_output(home: Path) -> None:
    _seed(
        home,
        "default_profile: prod\nprofiles:\n  prod: {url: https://nb1/, token: t1}\n",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["profiles", "list", "--output", "json"])
    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["default"] == "prod"
    assert any(p["name"] == "prod" for p in payload["profiles"])


@respx.mock
def test_profiles_add_writes_and_verifies(home: Path) -> None:
    _good_status()
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "profiles",
            "add",
            "prod",
            "--url",
            "https://nb.example/",
            "--token",
            "T123",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    body = (home / "config.yaml").read_text(encoding="utf-8")
    assert "prod:" in body
    assert "token: T123" in body


def test_profiles_remove_deletes_cache(home: Path) -> None:
    _seed(
        home,
        "default_profile: lab\n"
        "profiles:\n"
        "  prod: {url: https://nb1/, token: t1}\n"
        "  lab: {url: https://nb2/, token: t2}\n",
    )
    cache_dir = home / "cache" / "prod"
    cache_dir.mkdir(parents=True)
    (cache_dir / "stale.json").write_text("{}", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["profiles", "remove", "prod"])
    assert result.exit_code == 0, result.stdout + result.stderr
    body = (home / "config.yaml").read_text(encoding="utf-8")
    assert "prod" not in body
    assert not cache_dir.exists()


def test_profiles_remove_refuses_default_without_force(home: Path) -> None:
    _seed(
        home,
        "default_profile: prod\nprofiles:\n  prod: {url: https://nb1/, token: t1}\n",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["profiles", "remove", "prod"])
    assert result.exit_code != 0
    combined = result.stdout + result.stderr
    assert "default" in combined
    assert "prod" in (home / "config.yaml").read_text(encoding="utf-8")


def test_profiles_rename_updates_config_and_moves_cache(home: Path) -> None:
    _seed(
        home,
        "default_profile: prod\nprofiles:\n  prod: {url: https://nb1/, token: t1}\n",
    )
    cache_dir = home / "cache" / "prod"
    cache_dir.mkdir(parents=True)
    (cache_dir / "x.json").write_text("{}", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["profiles", "rename", "prod", "production"])
    assert result.exit_code == 0, result.stdout + result.stderr
    body = (home / "config.yaml").read_text(encoding="utf-8")
    assert "production:" in body
    assert "default_profile: production" in body
    assert not cache_dir.exists()
    assert (home / "cache" / "production" / "x.json").exists()


def test_profiles_set_default_updates_yaml(home: Path) -> None:
    _seed(
        home,
        "default_profile: prod\n"
        "profiles:\n"
        "  prod: {url: https://nb1/, token: t1}\n"
        "  lab: {url: https://nb2/, token: t2}\n",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["profiles", "set-default", "lab"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "default_profile: lab" in (home / "config.yaml").read_text(encoding="utf-8")


def test_profiles_set_default_rejects_unknown(home: Path) -> None:
    _seed(
        home,
        "profiles:\n  prod: {url: https://nb1/, token: t1}\n",
    )
    runner = CliRunner()
    result = runner.invoke(app, ["profiles", "set-default", "ghost"])
    assert result.exit_code != 0
