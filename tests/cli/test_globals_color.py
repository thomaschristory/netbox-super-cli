from __future__ import annotations

import sys

import pytest

from nsc.cli import globals as globals_mod
from nsc.cli.globals import GlobalState, build_runtime_context
from nsc.cli.runtime import CLIOverrides
from nsc.config.models import Config
from nsc.model.command_model import CommandModel


def _state() -> GlobalState:
    return GlobalState(overrides=CLIOverrides(), config=Config(), debug=False)


def _stub_command_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        globals_mod,
        "resolve_command_model",
        lambda **kwargs: CommandModel(info_title="t", info_version="v", schema_hash="x"),
    )


def test_build_runtime_context_gates_stderr_color_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """color (stdout) and color_stderr (stderr) must each follow their own TTY.

    Regression: build_runtime_context derived both flags from sys.stdout.isatty(),
    so `nsc ... 2>err.log` (stdout a TTY, stderr a file) leaked ANSI into the file.
    """
    monkeypatch.setenv("NSC_URL", "https://nb.example/")
    monkeypatch.setenv("NSC_TOKEN", "tok")
    for var in ("NSC_PROFILE", "NSC_SCHEMA", "NSC_OUTPUT"):
        monkeypatch.delenv(var, raising=False)
    _stub_command_model(monkeypatch)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)

    ctx = build_runtime_context(_state())

    assert ctx.color is True
    assert ctx.color_stderr is False


def test_build_runtime_context_gates_stdout_color_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reverse: stdout piped, stderr a TTY — error panels stay colored."""
    monkeypatch.setenv("NSC_URL", "https://nb.example/")
    monkeypatch.setenv("NSC_TOKEN", "tok")
    for var in ("NSC_PROFILE", "NSC_SCHEMA", "NSC_OUTPUT"):
        monkeypatch.delenv(var, raising=False)
    _stub_command_model(monkeypatch)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)

    ctx = build_runtime_context(_state())

    assert ctx.color is False
    assert ctx.color_stderr is True
