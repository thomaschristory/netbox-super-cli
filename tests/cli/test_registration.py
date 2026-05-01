from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import typer
from typer.testing import CliRunner

from nsc.cli.registration import register_dynamic_commands
from nsc.cli.runtime import ResolvedProfile, RuntimeContext
from nsc.config.models import Config, OutputFormat
from nsc.model.command_model import (
    CommandModel,
    HttpMethod,
    Operation,
    Parameter,
    ParameterLocation,
    PrimitiveType,
    Resource,
    Tag,
)


def _ctx(client: Any) -> RuntimeContext:
    return RuntimeContext(
        resolved_profile=ResolvedProfile(
            name="prod",
            url="https://nb.example/",
            token="t",
            verify_ssl=True,
            timeout=5.0,
            schema_url=None,
        ),
        config=Config(),
        command_model=MagicMock(),
        client=client,
        output_format=OutputFormat.JSON,
        fetch_all=True,
    )


def _model_with_list_op(parameters: list[Parameter]) -> CommandModel:
    op = Operation(
        operation_id="dcim_devices_list",
        http_method=HttpMethod.GET,
        path="/api/dcim/devices/",
        parameters=parameters,
    )
    resource = Resource(name="devices", list_op=op)
    tag = Tag(name="dcim", resources={"devices": resource})
    return CommandModel(
        info_title="t",
        info_version="1.0.0",
        schema_hash="h",
        tags={"dcim": tag},
    )


def test_registers_list_command_under_tag_resource() -> None:
    app = typer.Typer()
    client = MagicMock()
    client.paginate.return_value = iter([])
    model = _model_with_list_op([])
    ctx = _ctx(client)
    register_dynamic_commands(app, model, lambda: ctx)
    runner = CliRunner()
    result = runner.invoke(app, ["dcim", "devices", "list"])
    assert result.exit_code == 0
    client.paginate.assert_called_once_with("/api/dcim/devices/", {})


def test_typed_flag_from_string_query_param() -> None:
    app = typer.Typer()
    client = MagicMock()
    client.paginate.return_value = iter([])
    model = _model_with_list_op(
        [
            Parameter(
                name="status",
                location=ParameterLocation.QUERY,
                primitive=PrimitiveType.STRING,
            )
        ]
    )
    ctx = _ctx(client)
    register_dynamic_commands(app, model, lambda: ctx)
    result = CliRunner().invoke(app, ["dcim", "devices", "list", "--status", "active"])
    assert result.exit_code == 0
    client.paginate.assert_called_once_with("/api/dcim/devices/", {"status": "active"})


def test_typed_flag_with_underscore_becomes_hyphen() -> None:
    app = typer.Typer()
    client = MagicMock()
    client.paginate.return_value = iter([])
    model = _model_with_list_op(
        [
            Parameter(
                name="site_id",
                location=ParameterLocation.QUERY,
                primitive=PrimitiveType.INTEGER,
            )
        ]
    )
    ctx = _ctx(client)
    register_dynamic_commands(app, model, lambda: ctx)
    result = CliRunner().invoke(app, ["dcim", "devices", "list", "--site-id", "42"])
    assert result.exit_code == 0
    client.paginate.assert_called_once_with("/api/dcim/devices/", {"site_id": 42})


def test_double_underscore_param_is_skipped_typed_flag_but_filter_carries_it() -> None:
    app = typer.Typer()
    client = MagicMock()
    client.paginate.return_value = iter([])
    model = _model_with_list_op(
        [
            Parameter(
                name="created__gte",
                location=ParameterLocation.QUERY,
                primitive=PrimitiveType.STRING,
            )
        ]
    )
    ctx = _ctx(client)
    register_dynamic_commands(app, model, lambda: ctx)
    fail = CliRunner().invoke(app, ["dcim", "devices", "list", "--created-gte", "x"])
    assert fail.exit_code != 0
    ok = CliRunner().invoke(app, ["dcim", "devices", "list", "--filter", "created__gte=2026-01-01"])
    assert ok.exit_code == 0
    client.paginate.assert_called_once_with("/api/dcim/devices/", {"created__gte": "2026-01-01"})


def test_get_command_takes_path_var_as_positional() -> None:
    app = typer.Typer()
    client = MagicMock()
    client.get.return_value = {"id": 7}
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
            )
        ],
    )
    resource = Resource(name="devices", get_op=op)
    tag = Tag(name="dcim", resources={"devices": resource})
    model = CommandModel(info_title="t", info_version="1.0.0", schema_hash="h", tags={"dcim": tag})
    ctx = _ctx(client)
    register_dynamic_commands(app, model, lambda: ctx)
    result = CliRunner().invoke(app, ["dcim", "devices", "get", "7"])
    assert result.exit_code == 0
    client.get.assert_called_once_with("/api/dcim/devices/7/", {})


def test_post_patch_put_delete_are_skipped_in_phase_2() -> None:
    app = typer.Typer()
    client = MagicMock()
    create_op = Operation(
        operation_id="dcim_devices_create",
        http_method=HttpMethod.POST,
        path="/api/dcim/devices/",
        parameters=[],
    )
    delete_op = Operation(
        operation_id="dcim_devices_destroy",
        http_method=HttpMethod.DELETE,
        path="/api/dcim/devices/{id}/",
        parameters=[],
    )
    resource = Resource(name="devices", create_op=create_op, delete_op=delete_op)
    tag = Tag(name="dcim", resources={"devices": resource})
    model = CommandModel(info_title="t", info_version="1.0.0", schema_hash="h", tags={"dcim": tag})
    ctx = _ctx(client)
    register_dynamic_commands(app, model, lambda: ctx)
    result = CliRunner().invoke(app, ["dcim", "devices", "create"])
    assert result.exit_code != 0


def test_enum_param_becomes_choice() -> None:
    app = typer.Typer()
    client = MagicMock()
    client.paginate.return_value = iter([])
    model = _model_with_list_op(
        [
            Parameter(
                name="status",
                location=ParameterLocation.QUERY,
                primitive=PrimitiveType.STRING,
                enum=["active", "decommissioned"],
            )
        ]
    )
    ctx = _ctx(client)
    register_dynamic_commands(app, model, lambda: ctx)
    bad = CliRunner().invoke(app, ["dcim", "devices", "list", "--status", "garbage"])
    assert bad.exit_code != 0
    good = CliRunner().invoke(app, ["dcim", "devices", "list", "--status", "active"])
    assert good.exit_code == 0
