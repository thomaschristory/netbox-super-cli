from __future__ import annotations

import io
import json

import pytest
from ruamel.yaml import YAML

from nsc.config.models import OutputFormat
from nsc.output.render import render, select_format


def _safe_load(text: str) -> object:
    return YAML(typ="safe").load(io.StringIO(text))


def test_render_json_dispatches() -> None:
    buf = io.StringIO()
    render([{"id": 1}], format=OutputFormat.JSON, stream=buf)
    assert json.loads(buf.getvalue()) == [{"id": 1}]


def test_render_jsonl_dispatches() -> None:
    buf = io.StringIO()
    render([{"id": 1}, {"id": 2}], format=OutputFormat.JSONL, stream=buf)
    assert len([line for line in buf.getvalue().splitlines() if line]) == 2


def test_render_yaml_dispatches() -> None:
    buf = io.StringIO()
    render({"id": 1}, format=OutputFormat.YAML, stream=buf)
    assert _safe_load(buf.getvalue()) == {"id": 1}


def test_render_csv_dispatches() -> None:
    buf = io.StringIO()
    render([{"id": 1}], format=OutputFormat.CSV, columns=["id"], stream=buf)
    assert "id" in buf.getvalue() and "1" in buf.getvalue()


def test_render_table_dispatches() -> None:
    buf = io.StringIO()
    render([{"id": 1}], format=OutputFormat.TABLE, columns=["id"], stream=buf)
    assert "id" in buf.getvalue() and "1" in buf.getvalue()


def test_select_format_explicit_cli_wins() -> None:
    fmt = select_format(cli_value="csv", env_value="json", is_tty=True, default=OutputFormat.TABLE)
    assert fmt is OutputFormat.CSV


def test_select_format_env_used_when_cli_absent() -> None:
    fmt = select_format(cli_value=None, env_value="jsonl", is_tty=True, default=OutputFormat.TABLE)
    assert fmt is OutputFormat.JSONL


def test_select_format_falls_back_to_json_when_piped() -> None:
    fmt = select_format(cli_value=None, env_value=None, is_tty=False, default=OutputFormat.TABLE)
    assert fmt is OutputFormat.JSON


def test_select_format_uses_default_on_tty() -> None:
    fmt = select_format(cli_value=None, env_value=None, is_tty=True, default=OutputFormat.TABLE)
    assert fmt is OutputFormat.TABLE


def test_select_format_rejects_invalid_cli_value() -> None:
    with pytest.raises(ValueError):
        select_format(cli_value="xml", env_value=None, is_tty=True, default=OutputFormat.TABLE)
