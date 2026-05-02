from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import typer
from typer.testing import CliRunner

from nsc.builder.build import build_command_model
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
from nsc.schema.loader import load_schema


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


def test_post_and_delete_are_registered_in_phase_3b() -> None:
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
    closures = _collect_closures(app)
    cmds = closures.get(("dcim", "devices"), [])
    assert "create" in cmds
    assert "delete" in cmds


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


def test_array_param_becomes_repeatable_option() -> None:
    app = typer.Typer()
    client = MagicMock()
    client.paginate.return_value = iter([])
    model = _model_with_list_op(
        [
            Parameter(
                name="tag",
                location=ParameterLocation.QUERY,
                primitive=PrimitiveType.ARRAY,
            )
        ]
    )
    ctx = _ctx(client)
    register_dynamic_commands(app, model, lambda: ctx)
    result = CliRunner().invoke(app, ["dcim", "devices", "list", "--tag", "red", "--tag", "blue"])
    assert result.exit_code == 0, result.stdout
    client.paginate.assert_called_once_with("/api/dcim/devices/", {"tag": ["red", "blue"]})


def _stub_ctx(model: CommandModel) -> Any:
    """Minimal RuntimeContext stub for closure construction in unit tests."""
    return SimpleNamespace(command_model=model)


def _collect_closures(app: typer.Typer) -> dict[tuple[str, str], list[str]]:
    """Return {(tag, resource): [command_name, ...]} from a Typer app."""
    out: dict[tuple[str, str], list[str]] = {}
    for tag_info in app.registered_groups:
        tag_name = tag_info.name or ""
        tag_app = tag_info.typer_instance
        if tag_app is None:
            continue
        for res_info in tag_app.registered_groups:
            res_name = res_info.name or ""
            res_app = res_info.typer_instance
            if res_app is None:
                continue
            for cmd_info in res_app.registered_commands:
                if cmd_info.name:
                    out.setdefault((tag_name, res_name), []).append(cmd_info.name)
    return out


def test_create_command_registered_for_resource_with_create_op() -> None:
    loaded = load_schema("nsc/schemas/bundled/netbox-4.6.0-beta2.json.gz")
    model = build_command_model(loaded)
    sample_tag = "dcim"
    sample_resource = "devices"
    assert model.tags[sample_tag].resources[sample_resource].create_op is not None

    app = typer.Typer()
    register_dynamic_commands(app, model, lambda: _stub_ctx(model))
    closures = _collect_closures(app)
    assert any(
        name in {"create", "update", "delete"}
        for name in closures.get((sample_tag, sample_resource), [])
    )


def test_custom_action_post_registered_as_write_command() -> None:
    loaded = load_schema("nsc/schemas/bundled/netbox-4.6.0-beta2.json.gz")
    model = build_command_model(loaded)
    app = typer.Typer()
    register_dynamic_commands(app, model, lambda: _stub_ctx(model))
    closures = _collect_closures(app)
    assert any("available-asns" in name for name in closures.get(("ipam", "asn-ranges"), []))
