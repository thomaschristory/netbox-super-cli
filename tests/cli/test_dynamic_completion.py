"""Phase: dynamic shell completion (issue #2).

Drives the completion providers against a STUBBED on-disk cache + config and
asserts the suggested candidate lists for the three acceptance cases:

1. resource-name completion (`nsc ls dev<TAB>` -> devices, device-roles, ...)
2. `--profile <TAB>` -> profile names from config
3. enum completion (`--status <TAB>` -> active, decommissioning, ...)

All providers must be side-effect-free, read only the on-disk cache, and
degrade to `[]` when the cache/config is absent (never crash the shell).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nsc.completion import callbacks, providers
from nsc.completion.cache_probe import load_cached_model_for_profile, resolve_completion_profile
from nsc.config.models import Config, Profile
from nsc.config.settings import Paths
from nsc.model.command_model import (
    MODEL_FORMAT_VERSION,
    CommandModel,
    HttpMethod,
    Operation,
    Parameter,
    ParameterLocation,
    PrimitiveType,
    Resource,
    Tag,
)


def _model() -> CommandModel:
    list_op = Operation(
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
            Parameter(
                name="name",
                location=ParameterLocation.QUERY,
                primitive=PrimitiveType.STRING,
            ),
        ],
    )
    delete_op = Operation(
        operation_id="dcim_devices_destroy",
        http_method=HttpMethod.DELETE,
        path="/api/dcim/devices/{id}/",
    )
    devices = Resource(name="devices", list_op=list_op, delete_op=delete_op)
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
    sites = Resource(
        name="sites",
        list_op=Operation(
            operation_id="dcim_sites_list",
            http_method=HttpMethod.GET,
            path="/api/dcim/sites/",
        ),
    )
    dcim = Tag(
        name="dcim",
        resources={
            "devices": devices,
            "device-roles": device_roles,
            "device-types": device_types,
            "sites": sites,
        },
    )
    return CommandModel(
        info_title="t",
        info_version="1",
        schema_hash="0" * 64,
        tags={"dcim": dcim},
        format_version=MODEL_FORMAT_VERSION,
    )


def _write_cache(paths: Paths, profile: str, model: CommandModel) -> None:
    profile_dir = paths.cache_dir / profile
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / f"{model.schema_hash}.json").write_text(model.model_dump_json())
    (profile_dir / f"{model.schema_hash}.meta.json").write_text(json.dumps({"fetched_at": 1.0}))


def _config_path(paths: Paths) -> Path:
    paths.root.mkdir(parents=True, exist_ok=True)
    return paths.config_file


# --- resource-name completion --------------------------------------------


def test_resource_names_filtered_by_prefix() -> None:
    model = _model()
    names = providers.resource_name_candidates(model, verb="ls", incomplete="dev")
    assert names == ["device-roles", "device-types", "devices"]
    assert "sites" not in names


def test_resource_names_empty_prefix_lists_all_with_list_op() -> None:
    model = _model()
    names = providers.resource_name_candidates(model, verb="ls", incomplete="")
    assert names == ["device-roles", "device-types", "devices", "sites"]


def test_resource_names_for_rm_only_includes_delete_capable() -> None:
    model = _model()
    names = providers.resource_name_candidates(model, verb="rm", incomplete="dev")
    assert names == ["devices"]


def test_resource_names_none_model_returns_empty() -> None:
    assert providers.resource_name_candidates(None, verb="ls", incomplete="dev") == []


# --- profile-name completion ---------------------------------------------


def test_profile_candidates_from_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NSC_HOME", str(tmp_path))
    paths = Paths(root=tmp_path)
    cfg = _config_path(paths)
    cfg.write_text(
        "profiles:\n"
        "  prod:\n    url: https://nb.example.com\n"
        "  staging:\n    url: https://stg.example.com\n"
    )
    names = providers.profile_candidates(paths, incomplete="")
    assert names == ["prod", "staging"]
    assert providers.profile_candidates(paths, incomplete="pr") == ["prod"]


def test_profile_candidates_missing_config_returns_empty(tmp_path: Path) -> None:
    paths = Paths(root=tmp_path / "nope")
    assert providers.profile_candidates(paths, incomplete="") == []


# Enum completion (`--status <TAB>`) is exercised end-to-end in
# tests/cli/test_completion_protocol_smoke.py::test_enum_status_completion, which
# drives the real dynamic command tree and Click's native `Choice` completion —
# the actual production path. There is no standalone provider for it.


# --- cheap cache probe ----------------------------------------------------


def test_load_cached_model_reads_disk_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NSC_HOME", str(tmp_path))
    paths = Paths(root=tmp_path)
    model = _model()
    _write_cache(paths, "prod", model)
    loaded = load_cached_model_for_profile(paths, "prod")
    assert loaded is not None
    assert "dcim" in loaded.tags


def test_load_cached_model_absent_returns_none(tmp_path: Path) -> None:
    paths = Paths(root=tmp_path)
    assert load_cached_model_for_profile(paths, "prod") is None


def test_resolve_completion_profile_prefers_flag_then_env_then_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Config(
        default_profile="dfl",
        profiles={
            "dfl": Profile(name="dfl", url="https://a.example.com"),  # type: ignore[arg-type]
            "envp": Profile(name="envp", url="https://b.example.com"),  # type: ignore[arg-type]
            "flagp": Profile(name="flagp", url="https://c.example.com"),  # type: ignore[arg-type]
        },
    )
    monkeypatch.delenv("NSC_PROFILE", raising=False)
    assert resolve_completion_profile(config, args=[], env={}) == "dfl"
    assert resolve_completion_profile(config, args=[], env={"NSC_PROFILE": "envp"}) == "envp"
    assert (
        resolve_completion_profile(config, args=["--profile", "flagp"], env={"NSC_PROFILE": "envp"})
        == "flagp"
    )


# --- end-to-end via Typer shell_complete callbacks -----------------------


def test_alias_argument_shell_complete_uses_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `ls` argument's shell_complete must surface resource names from the
    on-disk cache with NO network and NO crash on the happy path."""
    monkeypatch.setenv("NSC_HOME", str(tmp_path))
    paths = Paths(root=tmp_path)
    cfg = _config_path(paths)
    cfg.write_text("default_profile: prod\nprofiles:\n  prod:\n    url: https://nb.example.com\n")
    _write_cache(paths, "prod", _model())

    items = callbacks.complete_resource_name("ls", incomplete="dev")
    values = [it.value if hasattr(it, "value") else it for it in items]
    assert "devices" in values
    assert "device-roles" in values
    assert "sites" not in values


def test_profile_shell_complete_callback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NSC_HOME", str(tmp_path))
    paths = Paths(root=tmp_path)
    cfg = _config_path(paths)
    cfg.write_text("profiles:\n  prod:\n    url: https://nb.example.com\n")

    items = callbacks.complete_profile(incomplete="pr")
    values = [it.value if hasattr(it, "value") else it for it in items]
    assert values == ["prod"]


def test_callbacks_never_raise_on_missing_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NSC_HOME", str(tmp_path / "empty"))

    assert callbacks.complete_resource_name("ls", incomplete="dev") == []
    assert callbacks.complete_profile(incomplete="x") == []
