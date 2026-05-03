"""Phase 5a — verify Typer's static --install-completion produces a script."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from nsc.cli.app import app


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish", "pwsh"])
def test_install_completion_produces_a_script(shell: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """`nsc --show-completion <shell>` must exit 0 and emit a non-empty script.

    Typer wires this for free when `Typer(name=..., add_completion=True)`. This
    test guards against accidental removal of either flag in nsc/cli/app.py.

    `_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION` switches Typer's
    `--show-completion` from auto-detect (no value) to taking the shell as a
    flag value, so we can exercise all four shells deterministically.
    """
    monkeypatch.setenv("_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION", "1")
    runner = CliRunner()
    result = runner.invoke(app, ["--show-completion", shell])
    assert result.exit_code == 0, result.output
    assert result.output.strip(), f"empty completion script for {shell}: {result.output!r}"
