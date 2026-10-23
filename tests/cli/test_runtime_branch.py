from __future__ import annotations

from pathlib import Path

import pytest

from nsc.branching.errors import (
    BranchConflictError,
    BranchingNotInstalledError,
    BranchJobFailedError,
    BranchJobTimeoutError,
    BranchNotFoundError,
    BranchNotReadyError,
)
from nsc.cli import globals as globals_mod
from nsc.cli.app import _extract_global_overrides, _first_non_option
from nsc.cli.globals import GlobalState, build_runtime_context
from nsc.cli.runtime import BranchSelection, CLIOverrides, map_error, resolve_branch_selection
from nsc.config.loader import load_config
from nsc.config.models import Config, Profile
from nsc.model.command_model import CommandModel
from nsc.output.errors import ErrorType


def _cfg(branch: str | None = "prof-branch") -> Config:
    return Config(
        default_profile="p",
        profiles={"p": Profile(name="p", url="https://nb.example", token="t", branch=branch)},
    )


def test_branch_flag_beats_env_and_profile() -> None:
    sel = resolve_branch_selection(_cfg(), CLIOverrides(branch="f"), env={"NSC_BRANCH": "e"})
    assert sel == BranchSelection(name="f", source="flag")


def test_branch_env_beats_profile() -> None:
    sel = resolve_branch_selection(_cfg(), CLIOverrides(), env={"NSC_BRANCH": "e"})
    assert sel == BranchSelection(name="e", source="env")


def test_branch_from_profile() -> None:
    sel = resolve_branch_selection(_cfg(), CLIOverrides(), env={})
    assert sel == BranchSelection(name="prof-branch", source="profile")


def test_branch_main_forces_none() -> None:
    assert resolve_branch_selection(_cfg(), CLIOverrides(branch="main"), env={}) is None
    assert resolve_branch_selection(_cfg(), CLIOverrides(), env={"NSC_BRANCH": "main"}) is None


def test_empty_env_branch_is_unset() -> None:
    sel = resolve_branch_selection(_cfg(), CLIOverrides(), env={"NSC_BRANCH": ""})
    assert sel == BranchSelection(name="prof-branch", source="profile")


def test_no_branch_anywhere_is_none() -> None:
    assert resolve_branch_selection(_cfg(branch=None), CLIOverrides(), env={}) is None
    assert resolve_branch_selection(Config(), CLIOverrides(), env={}) is None


def test_extract_global_overrides_reads_branch() -> None:
    assert _extract_global_overrides(["--branch", "x", "dcim"]).branch == "x"
    assert _extract_global_overrides(["--branch=y", "dcim"]).branch == "y"


def test_profile_accepts_branch_field(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "default_profile: p\nprofiles:\n  p:\n    url: https://nb.example\n    token: t\n"
        "    branch: my-change\n"
    )
    assert load_config(cfg_file).profiles["p"].branch == "my-change"


def _stub_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NSC_URL", "https://nb.example/")
    monkeypatch.setenv("NSC_TOKEN", "tok")
    for var in ("NSC_PROFILE", "NSC_SCHEMA", "NSC_OUTPUT", "NSC_BRANCH"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(
        globals_mod,
        "resolve_command_model",
        lambda **kwargs: CommandModel(info_title="t", info_version="v", schema_hash="x"),
    )


def test_stderr_notice_printed_when_branch_active(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_env(monkeypatch)
    state = GlobalState(overrides=CLIOverrides(branch="my-change"), config=Config(), debug=False)
    ctx = build_runtime_context(state)
    out = capsys.readouterr()
    assert out.err == "⎇ branch: my-change\n"
    assert out.out == ""
    assert ctx.branch == BranchSelection(name="my-change", source="flag")


def test_no_notice_without_branch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_env(monkeypatch)
    ctx = build_runtime_context(GlobalState(overrides=CLIOverrides(), config=Config(), debug=False))
    assert capsys.readouterr().err == ""
    assert ctx.branch is None


@pytest.mark.parametrize(
    ("exc", "etype"),
    [
        (BranchingNotInstalledError(), ErrorType.CONFIG),
        (BranchNotFoundError("x"), ErrorType.NOT_FOUND),
        (BranchNotReadyError("x", "merged"), ErrorType.CONFIG),
        (BranchConflictError("x", [{"id": 6, "conflicts": ["name"]}]), ErrorType.CONFLICT),
        (BranchJobFailedError("x", {"id": 7, "error": "nope"}), ErrorType.VALIDATION),
        (BranchJobTimeoutError("x", 7), ErrorType.TRANSPORT),
    ],
)
def test_map_error_branch_errors(exc: Exception, etype: ErrorType) -> None:
    env = map_error(exc)
    assert env.type is etype
    if not isinstance(exc, BranchingNotInstalledError):
        assert env.details["branch"] == "x"


def test_map_error_conflict_details_carry_conflicts() -> None:
    env = map_error(BranchConflictError("x", [{"id": 6, "conflicts": ["name"]}]))
    assert env.details["conflicts"] == [{"id": 6, "conflicts": ["name"]}]


def test_map_error_job_failed_details() -> None:
    env = map_error(BranchJobFailedError("x", {"id": 7, "error": "nope"}))
    assert env.details["job_id"] == 7
    assert env.details["job_error"] == "nope"


def test_branch_after_subcommand_is_not_global() -> None:
    # A dynamic command's own --branch filter (e.g. the plugin's changes list)
    # must not switch the whole invocation into a branch.
    args = ["plugins", "branching", "changes", "list", "--branch", "x"]
    assert _extract_global_overrides(args).branch is None
    assert _extract_global_overrides([*args[:-2], "--branch=x"]).branch is None


def test_branch_before_subcommand_is_global_and_other_flags_still_scan() -> None:
    overrides = _extract_global_overrides(
        ["--profile", "p", "--branch", "x", "dcim", "sites", "list", "--output", "json"]
    )
    assert overrides.branch == "x"
    assert overrides.profile == "p"
    assert overrides.output == "json"


def test_first_non_option_skips_branch_value() -> None:
    assert _first_non_option(["--branch", "x", "profiles", "list"]) == "profiles"
    assert _first_non_option(["--branch=x", "profiles", "list"]) == "profiles"


@pytest.mark.parametrize(
    ("overrides", "env"),
    [
        (CLIOverrides(url="https://other.example"), {}),
        (CLIOverrides(), {"NSC_URL": "https://other.example/"}),
    ],
)
def test_profile_branch_ignored_when_url_targets_another_server(
    overrides: CLIOverrides, env: dict[str, str]
) -> None:
    assert resolve_branch_selection(_cfg(), overrides, env=env) is None


@pytest.mark.parametrize("url", ["https://nb.example", "https://nb.example/", "https://NB.example"])
def test_profile_branch_kept_when_url_override_matches_profile(url: str) -> None:
    sel = resolve_branch_selection(_cfg(), CLIOverrides(url=url), env={})
    assert sel == BranchSelection(name="prof-branch", source="profile")


def test_explicit_branch_still_applies_with_url_override() -> None:
    other = CLIOverrides(url="https://other.example")
    assert resolve_branch_selection(_cfg(), other, env={"NSC_BRANCH": "e"}) == BranchSelection(
        name="e", source="env"
    )
    with_flag = CLIOverrides(url="https://other.example", branch="f")
    assert resolve_branch_selection(_cfg(), with_flag, env={}) == BranchSelection(
        name="f", source="flag"
    )
