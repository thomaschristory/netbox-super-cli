"""Unit tests for handler-level helpers that lock the agent contract.

The integration suite in tests/cli/test_writes_respx.py (Task 11) covers
end-to-end CLI invocation. These tests pin specific output shapes that are
documented as the agent contract (delete responses, preflight envelope).
"""

from __future__ import annotations

import io
import json
import re

from pydantic import HttpUrl

from nsc.cli.handlers import (
    _extract_path_vars,
    _preflight_envelope,
    _render_delete_already_absent,
    _render_delete_ok,
)
from nsc.cli.runtime import ResolvedProfile, RuntimeContext
from nsc.cli.writes.preflight import Issue, PreflightResult
from nsc.config.models import Config, OutputFormat
from nsc.http.client import NetBoxClient
from nsc.model.command_model import (
    CommandModel,
    HttpMethod,
    Operation,
    Parameter,
    ParameterLocation,
    PrimitiveType,
)


class _Profile:
    url = "https://nb.example"
    token = "t0ken"
    verify_ssl = True
    timeout = 5.0


def strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def _ctx(output_format: OutputFormat) -> RuntimeContext:
    profile = ResolvedProfile(
        name="test",
        url=HttpUrl("https://nb.example"),
        token="t0ken",
        verify_ssl=True,
        timeout=5.0,
        schema_url=None,
    )
    return RuntimeContext(
        resolved_profile=profile,
        config=Config(),
        command_model=CommandModel(info_title="t", info_version="v", schema_hash="x"),
        client=NetBoxClient(_Profile()),
        output_format=output_format,
    )


def _ctx_color(output_format: OutputFormat, *, color: bool) -> RuntimeContext:
    profile = ResolvedProfile(
        name="test",
        url=HttpUrl("https://nb.example"),
        token="t0ken",
        verify_ssl=True,
        timeout=5.0,
        schema_url=None,
    )
    return RuntimeContext(
        resolved_profile=profile,
        config=Config(),
        command_model=CommandModel(info_title="t", info_version="v", schema_hash="x"),
        client=NetBoxClient(_Profile()),
        output_format=output_format,
        color=color,
    )


def test_extract_path_vars_filters_to_path_params_and_strips_none() -> None:
    op = Operation(
        operation_id="dcim_devices_partial_update",
        http_method=HttpMethod.PATCH,
        path="/api/dcim/devices/{id}/",
        parameters=[
            Parameter(name="id", location=ParameterLocation.PATH, primitive=PrimitiveType.INTEGER),
            Parameter(
                name="cursor", location=ParameterLocation.QUERY, primitive=PrimitiveType.STRING
            ),
        ],
    )
    kwargs = {"id": 42, "cursor": "p2", "noise": None, "unrelated": "x"}
    assert _extract_path_vars(op, kwargs) == {"id": "42"}


def test_render_delete_ok_json_shape() -> None:
    buf = io.StringIO()
    _render_delete_ok(_ctx(OutputFormat.JSON), stream=buf)
    assert json.loads(buf.getvalue()) == {"deleted": True}


def test_render_delete_ok_table_text() -> None:
    buf = io.StringIO()
    _render_delete_ok(_ctx(OutputFormat.TABLE), stream=buf)
    assert "deleted" in buf.getvalue()


def test_render_delete_already_absent_json_shape() -> None:
    buf = io.StringIO()
    _render_delete_already_absent(_ctx(OutputFormat.JSON), stream=buf)
    assert json.loads(buf.getvalue()) == {"deleted": False, "reason": "already_absent"}


def test_render_delete_already_absent_table_text() -> None:
    buf = io.StringIO()
    _render_delete_already_absent(_ctx(OutputFormat.TABLE), stream=buf)
    assert "absent" in buf.getvalue().lower()


def test_render_delete_ok_table_color_false_plain() -> None:
    buf = io.StringIO()
    _render_delete_ok(_ctx_color(OutputFormat.TABLE, color=False), stream=buf)
    assert buf.getvalue() == "deleted\n"


def test_render_delete_ok_table_color_true_has_ansi() -> None:
    buf = io.StringIO()
    _render_delete_ok(_ctx_color(OutputFormat.TABLE, color=True), stream=buf)
    out = buf.getvalue()
    assert "\x1b[" in out
    assert "deleted" in strip_ansi(out)


def test_render_delete_already_absent_color_false_plain() -> None:
    buf = io.StringIO()
    _render_delete_already_absent(_ctx_color(OutputFormat.TABLE, color=False), stream=buf)
    assert buf.getvalue() == "already absent (no change)\n"


def test_render_delete_already_absent_color_true_has_ansi() -> None:
    buf = io.StringIO()
    _render_delete_already_absent(_ctx_color(OutputFormat.TABLE, color=True), stream=buf)
    out = buf.getvalue()
    assert "\x1b[" in out
    assert "already absent" in strip_ansi(out)


def test_preflight_envelope_shape() -> None:
    op = Operation(
        operation_id="dcim_devices_create",
        http_method=HttpMethod.POST,
        path="/api/dcim/devices/",
    )
    pre = PreflightResult(
        ok=False,
        issues=[
            Issue(
                record_index=0,
                field_path="name",
                kind="missing_required",
                message="required field 'name' is missing",
            )
        ],
    )
    env = _preflight_envelope(op, pre, applied=False)
    assert env.error == "preflight validation failed"
    assert env.operation_id == "dcim_devices_create"
    assert env.details["source"] == "preflight"
    assert env.details["applied"] is False
    assert env.details["issues"] == [
        {
            "record_index": 0,
            "field_path": "name",
            "kind": "missing_required",
            "message": "required field 'name' is missing",
            "expected": None,
        }
    ]
