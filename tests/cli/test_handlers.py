from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import MagicMock

import pytest
import typer

from nsc.cli.handlers import handle_custom_action, handle_get, handle_list, parse_filters
from nsc.cli.runtime import ResolvedProfile, RuntimeContext, apply_limit
from nsc.config.models import Config, OutputFormat
from nsc.http.errors import NetBoxAPIError
from nsc.model.command_model import (
    HttpMethod,
    Operation,
    Parameter,
    ParameterLocation,
    PrimitiveType,
)


def _ctx(client: Any, **overrides: Any) -> RuntimeContext:
    rp = ResolvedProfile(
        name="prod",
        url="https://nb.example/",
        token="t",
        verify_ssl=True,
        timeout=5.0,
        schema_url=None,
    )
    base: dict[str, Any] = {
        "resolved_profile": rp,
        "config": Config(),
        "command_model": MagicMock(),
        "client": client,
        "output_format": OutputFormat.JSON,
        "page_size": 50,
    }
    base.update(overrides)
    return RuntimeContext(**base)


def test_parse_filters_splits_repeated_kv() -> None:
    out = parse_filters(["site_id=42", "status=active"])
    assert out == {"site_id": "42", "status": "active"}


def test_parse_filters_rejects_malformed() -> None:
    with pytest.raises(ValueError):
        parse_filters(["bare"])


def test_handle_list_paginates_and_renders() -> None:
    client = MagicMock()
    client.paginate.return_value = iter([{"id": 1}, {"id": 2}, {"id": 3}])
    op = Operation(
        operation_id="dcim_devices_list",
        http_method=HttpMethod.GET,
        path="/api/dcim/devices/",
        parameters=[
            Parameter(
                name="site_id",
                location=ParameterLocation.QUERY,
                primitive=PrimitiveType.INTEGER,
            ),
        ],
    )
    buf = io.StringIO()
    ctx = _ctx(client, output_format=OutputFormat.JSON, fetch_all=True)
    handle_list(op, "dcim", "devices", ctx, stream=buf, site_id=42)
    client.paginate.assert_called_once_with("/api/dcim/devices/", {"site_id": 42})
    assert json.loads(buf.getvalue()) == [{"id": 1}, {"id": 2}, {"id": 3}]


def test_handle_list_applies_limit() -> None:
    client = MagicMock()
    client.paginate.return_value = iter([{"id": i} for i in range(10)])
    op = Operation(
        operation_id="x",
        http_method=HttpMethod.GET,
        path="/api/x/",
        parameters=[],
    )
    buf = io.StringIO()
    ctx = _ctx(client, output_format=OutputFormat.JSON, limit=3)
    handle_list(op, "t", "r", ctx, stream=buf)
    assert json.loads(buf.getvalue()) == [{"id": 0}, {"id": 1}, {"id": 2}]


def test_handle_list_merges_filter_flag_with_typed_kwargs() -> None:
    client = MagicMock()
    client.paginate.return_value = iter([])
    op = Operation(
        operation_id="x",
        http_method=HttpMethod.GET,
        path="/api/x/",
        parameters=[
            Parameter(
                name="status",
                location=ParameterLocation.QUERY,
                primitive=PrimitiveType.STRING,
            ),
        ],
    )
    buf = io.StringIO()
    ctx = _ctx(client, filters=[("created__gte", "2026-01-01")], fetch_all=True)
    handle_list(op, "t", "r", ctx, stream=buf, status="active")
    client.paginate.assert_called_once_with(
        "/api/x/", {"status": "active", "created__gte": "2026-01-01"}
    )


def test_handle_get_fills_path_var_and_renders_object() -> None:
    client = MagicMock()
    client.get.return_value = {"id": 7, "name": "x"}
    op = Operation(
        operation_id="dcim_devices_retrieve",
        http_method=HttpMethod.GET,
        path="/api/dcim/devices/{id}/",
        parameters=[
            Parameter(
                name="id",
                location=ParameterLocation.PATH,
                primitive=PrimitiveType.INTEGER,
                required=True,
            ),
        ],
    )
    buf = io.StringIO()
    ctx = _ctx(client, output_format=OutputFormat.JSON)
    handle_get(op, "dcim", "devices", ctx, stream=buf, id=7)
    client.get.assert_called_once_with("/api/dcim/devices/7/", {})
    assert json.loads(buf.getvalue()) == {"id": 7, "name": "x"}


def test_handle_custom_action_mirrors_get() -> None:
    client = MagicMock()
    client.get.return_value = {"available": []}
    op = Operation(
        operation_id="ipam_prefixes_available_ips_list",
        http_method=HttpMethod.GET,
        path="/api/ipam/prefixes/{id}/available-ips/",
        parameters=[
            Parameter(
                name="id",
                location=ParameterLocation.PATH,
                primitive=PrimitiveType.INTEGER,
                required=True,
            ),
        ],
    )
    buf = io.StringIO()
    ctx = _ctx(client, output_format=OutputFormat.JSON)
    handle_custom_action(op, "ipam", "prefixes", ctx, stream=buf, id=12)
    client.get.assert_called_once_with("/api/ipam/prefixes/12/available-ips/", {})


def test_apply_limit_first_page_default() -> None:
    out = list(apply_limit(iter(range(100)), limit=None, fetch_all=False, page_size=50))
    assert out == list(range(50))


def test_apply_limit_all_drains_iterator() -> None:
    out = list(apply_limit(iter(range(7)), limit=None, fetch_all=True, page_size=50))
    assert out == list(range(7))


def test_apply_limit_with_explicit_limit() -> None:
    out = list(apply_limit(iter(range(100)), limit=3, fetch_all=False, page_size=50))
    assert out == [0, 1, 2]


def test_apply_limit_with_limit_and_all_limit_wins() -> None:
    out = list(apply_limit(iter(range(100)), limit=3, fetch_all=True, page_size=50))
    assert out == [0, 1, 2]


def test_handle_list_emits_envelope_on_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """handle_list should catch NetBoxAPIError and exit with mapped code."""
    operation = Operation(
        operation_id="dcim_devices_list",
        http_method=HttpMethod.GET,
        path="/api/dcim/devices/",
    )
    client = MagicMock()
    client.paginate.side_effect = NetBoxAPIError(
        status_code=404,
        url="https://nb/api/dcim/devices/",
        body_snippet="not found",
        headers={},
    )
    ctx = _ctx(client, output_format=OutputFormat.JSON)
    buf = io.StringIO()
    with pytest.raises(typer.Exit) as ei:
        handle_list(operation, "dcim", "devices", ctx, stream=buf)
    assert ei.value.exit_code == 9  # EXIT_CODES[ErrorType.NOT_FOUND]
