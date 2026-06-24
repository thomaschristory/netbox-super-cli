from __future__ import annotations

from typing import Any

import pytest
import typer
from typer.testing import CliRunner

import nsc.tui
from nsc.cli import tui_commands
from nsc.cli.app import app as real_app
from nsc.cli.tui_commands import _runtime_from_ctx, register
from nsc.config import settings


def test_tui_help_lists_resource_argument() -> None:
    result = CliRunner().invoke(real_app, ["tui", "--help"])
    assert result.exit_code == 0
    assert "resource" in result.output.lower()


def _help_app() -> typer.Typer:
    app = typer.Typer()
    register(app)
    return app


class _FakeConfig:
    def __init__(self) -> None:
        self.columns: dict[str, dict[str, list[str]]] = {}


class _FakeRuntime:
    def __init__(self) -> None:
        self.command_model = object()
        self.client = object()
        self.config = _FakeConfig()


def test_invoking_tui_calls_run_tui_with_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _FakeRuntime()
    calls: list[tuple[Any, Any, str | None]] = []

    def _fake_run_tui(
        model: Any,
        client: Any,
        *,
        initial_resource: str | None = None,
        save_columns: Any = None,
        column_prefs: Any = None,
    ) -> None:
        calls.append((model, client, initial_resource))

    monkeypatch.setattr(nsc.tui, "run_tui", _fake_run_tui)
    monkeypatch.setattr("nsc.cli.tui_commands._runtime_from_ctx", lambda _ctx: runtime)

    app = typer.Typer()
    register(app)
    result = CliRunner().invoke(app, ["tui", "devices"], obj=(None, runtime))
    assert result.exit_code == 0, result.output
    assert calls == [(runtime.command_model, runtime.client, "devices")]


def test_interactive_and_i_are_aliases_of_tui() -> None:
    for name in ("tui", "interactive", "i"):
        result = CliRunner().invoke(real_app, [name, "--help"])
        assert result.exit_code == 0, f"{name}: {result.output}"
        assert "resource" in result.output.lower()


def test_tui_is_visible_and_aliases_are_hidden() -> None:
    group = typer.main.get_command(_help_app())
    assert group.commands["tui"].hidden is False  # type: ignore[attr-defined]
    assert group.commands["interactive"].hidden is True  # type: ignore[attr-defined]
    assert group.commands["i"].hidden is True  # type: ignore[attr-defined]


def test_save_columns_persists_to_config(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("")

    class _Paths:
        @property
        def config_file(self) -> Any:
            return config_file

    monkeypatch.setattr(settings, "default_paths", _Paths)

    tui_commands._save_columns("dcim", "devices", ["id", "name"])

    text = config_file.read_text()
    assert "columns:" in text
    assert "dcim:" in text
    assert "devices:" in text
    assert "name" in text


def test_malformed_ctx_obj_exits_2() -> None:
    ctx = typer.Context(typer.main.get_command(_help_app()))
    ctx.obj = "not-a-tuple"
    with pytest.raises(typer.Exit) as exc:
        _runtime_from_ctx(ctx)
    assert exc.value.exit_code == 2


def test_missing_ctx_obj_exits_2() -> None:
    ctx = typer.Context(typer.main.get_command(_help_app()))
    ctx.obj = None
    with pytest.raises(typer.Exit) as exc:
        _runtime_from_ctx(ctx)
    assert exc.value.exit_code == 2
