"""Tests for `nsc commands`, the model-dump meta-command."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from nsc.cli.app import app


def _bundled_schema() -> Path:
    bundled = Path(__file__).resolve().parents[2] / "nsc" / "schemas" / "bundled"
    candidates = sorted(bundled.glob("netbox-*.json.gz"))
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


def test_insecure_flag_propagates_to_schema_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`nsc --insecure commands --schema https://...` must call httpx with verify=False.

    Regression for issue #8 — the `commands` meta-command bypasses the bootstrap
    pipeline that resolves `--insecure`, so it has to read the global state itself.
    """
    captured: dict[str, Any] = {}
    schema_body = gzip.decompress(_bundled_schema().read_bytes())

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        captured["url"] = url
        captured["verify"] = kwargs.get("verify")
        captured["timeout"] = kwargs.get("timeout")
        return httpx.Response(200, content=schema_body)

    monkeypatch.setattr("nsc.schema.loader.httpx.get", fake_get)
    monkeypatch.delenv("NSC_INSECURE", raising=False)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["--insecure", "commands", "--schema", "https://netbox.test.net/api/schema/?json"],
    )
    assert result.exit_code == 0, result.stderr
    assert captured["verify"] is False


def test_nsc_insecure_env_propagates_to_schema_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    schema_body = gzip.decompress(_bundled_schema().read_bytes())

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        captured["verify"] = kwargs.get("verify")
        return httpx.Response(200, content=schema_body)

    monkeypatch.setattr("nsc.schema.loader.httpx.get", fake_get)
    monkeypatch.setenv("NSC_INSECURE", "1")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["commands", "--schema", "https://netbox.test.net/api/schema/?json"],
    )
    assert result.exit_code == 0, result.stderr
    assert captured["verify"] is False


def test_default_keeps_ssl_verification_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    schema_body = gzip.decompress(_bundled_schema().read_bytes())

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        captured["verify"] = kwargs.get("verify")
        return httpx.Response(200, content=schema_body)

    monkeypatch.setattr("nsc.schema.loader.httpx.get", fake_get)
    monkeypatch.delenv("NSC_INSECURE", raising=False)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["commands", "--schema", "https://netbox.test.net/api/schema/?json"],
    )
    assert result.exit_code == 0, result.stderr
    assert captured["verify"] is True
