"""CI smoke test: drive Click's completion protocol end-to-end with a STUBBED
on-disk schema/config and assert the suggested candidate lists.

Extends the Phase-5a static-completion smoke (`test_completion_smoke.py`) with
the dynamic side (issue #2). Uses `ShellComplete.get_completions(args,
incomplete)` — the same entry point a real shell drives via `_NSC_COMPLETE` —
so this exercises the real callbacks and the cache-only `make_context`
fast-path. No network: any attempt to fetch a schema would hang/fail CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Typer vendors its own click (typer >= 0.26); driving completion with the
# standalone `click.shell_completion.ShellComplete` mis-resolves the
# vendored-click command tree. Use Typer's concrete BashComplete instead — it
# is the exact class a real bash shell would instantiate.
from typer._completion_classes import BashComplete
from typer.main import get_command

from nsc.cli.app import app
from nsc.config.settings import Paths
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


def _stub_model() -> CommandModel:
    devices = Resource(
        name="devices",
        list_op=Operation(
            operation_id="dcim_devices_list",
            http_method=HttpMethod.GET,
            path="/api/dcim/devices/",
            parameters=[
                Parameter(
                    name="status",
                    location=ParameterLocation.QUERY,
                    primitive=PrimitiveType.STRING,
                    enum=["active", "decommissioning", "offline", "planned"],
                ),
            ],
        ),
        delete_op=Operation(
            operation_id="dcim_devices_destroy",
            http_method=HttpMethod.DELETE,
            path="/api/dcim/devices/{id}/",
        ),
    )
    device_roles = Resource(
        name="device-roles",
        list_op=Operation(
            operation_id="dcim_device_roles_list",
            http_method=HttpMethod.GET,
            path="/api/dcim/device-roles/",
        ),
    )
    device_types = Resource(
        name="device-types",
        list_op=Operation(
            operation_id="dcim_device_types_list",
            http_method=HttpMethod.GET,
            path="/api/dcim/device-types/",
        ),
    )
    dcim = Tag(
        name="dcim",
        resources={
            "devices": devices,
            "device-roles": device_roles,
            "device-types": device_types,
        },
    )
    return CommandModel(
        info_title="t",
        info_version="1",
        schema_hash="a" * 64,
        tags={"dcim": dcim},
    )


@pytest.fixture
def stubbed_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Paths:
    monkeypatch.setenv("NSC_HOME", str(tmp_path))
    # Tell Click we are in completion mode so make_context takes the
    # cache-only path and never fetches a schema.
    monkeypatch.setenv("_NSC_COMPLETE", "complete")
    paths = Paths(root=tmp_path)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.config_file.write_text(
        "default_profile: prod\n"
        "profiles:\n"
        "  prod:\n    url: https://nb.example.com\n"
        "  staging:\n    url: https://stg.example.com\n"
    )
    model = _stub_model()
    profile_dir = paths.cache_dir / "prod"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / f"{model.schema_hash}.json").write_text(model.model_dump_json())
    (profile_dir / f"{model.schema_hash}.meta.json").write_text(json.dumps({"fetched_at": 1.0}))
    return paths


def _completions(args: list[str], incomplete: str) -> list[str]:
    cmd = get_command(app)
    completer = BashComplete(cmd, {}, "nsc", "_NSC_COMPLETE")
    return [c.value for c in completer.get_completions(args, incomplete)]


def test_resource_name_completion(stubbed_home: Paths) -> None:
    values = _completions(["ls"], "dev")
    assert "devices" in values
    assert "device-roles" in values
    assert "device-types" in values


def test_rm_resource_completion_only_delete_capable(stubbed_home: Paths) -> None:
    values = _completions(["rm"], "dev")
    assert values == ["devices"]


def test_profile_completion(stubbed_home: Paths) -> None:
    values = _completions(["--profile"], "")
    assert "prod" in values
    assert "staging" in values
    assert _completions(["--profile"], "st") == ["staging"]


def test_enum_status_completion(stubbed_home: Paths) -> None:
    values = _completions(["dcim", "devices", "list", "--status"], "")
    assert values == ["active", "decommissioning", "offline", "planned"]
    assert _completions(["dcim", "devices", "list", "--status"], "dec") == ["decommissioning"]


def test_completion_with_missing_cache_does_not_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NSC_HOME", str(tmp_path / "empty"))
    monkeypatch.setenv("_NSC_COMPLETE", "complete")
    # No cache, no config: completion returns nothing but never raises.
    assert _completions(["ls"], "dev") == []
    assert _completions(["--profile"], "") == []
