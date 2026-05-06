"""`nsc skill` — install the bundled portable Skill into agent harnesses.

Phase 5c ships `install`. Default behavior is dry-run; `--apply` copies the
bundled `SKILL.md` to each target's documented Skills directory. Targets
whose convention is unknown print actionable manual instructions instead of
guessing a path silently.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from nsc.skill import BUNDLE_NAME, bundle_path


class _Target(StrEnum):
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"
    GEMINI = "gemini"
    COPILOT = "copilot"


class _OutputFormat(StrEnum):
    TABLE = "table"
    JSON = "json"


@dataclass(frozen=True, slots=True)
class _Resolution:
    target: _Target
    path: Path | None
    manual_instructions: str | None


def _home() -> Path:
    return Path(os.environ.get("HOME") or os.path.expanduser("~"))


def _resolve_claude_code() -> _Resolution:
    return _Resolution(
        target=_Target.CLAUDE_CODE,
        path=_home() / ".claude" / "skills" / BUNDLE_NAME / "SKILL.md",
        manual_instructions=None,
    )


def _resolve_codex() -> _Resolution:
    # Per T1 research (developers.openai.com/codex/skills): Codex CLI loads
    # user-scoped skills from $HOME/.agents/skills/<name>/SKILL.md. The
    # `.agents/` prefix is agent-tool-neutral, not codex-specific.
    return _Resolution(
        target=_Target.CODEX,
        path=_home() / ".agents" / "skills" / BUNDLE_NAME / "SKILL.md",
        manual_instructions=None,
    )


def _resolve_gemini() -> _Resolution:
    return _Resolution(
        target=_Target.GEMINI,
        path=None,
        manual_instructions=(
            "Gemini CLI does not document a programmatic Skill install path "
            "as of this nsc release. To use the bundled Skill: paste its "
            "content into a project-scoped GEMINI.md or your Gemini system "
            "prompt."
        ),
    )


def _resolve_copilot() -> _Resolution:
    return _Resolution(
        target=_Target.COPILOT,
        path=None,
        manual_instructions=(
            "GitHub Copilot CLI does not document a stable user-scoped Skill "
            "install path as of this nsc release. To use the bundled Skill: "
            "paste its content into .github/copilot-instructions.md or your "
            "team's Copilot configuration."
        ),
    )


_RESOLVERS = {
    _Target.CLAUDE_CODE: _resolve_claude_code,
    _Target.CODEX: _resolve_codex,
    _Target.GEMINI: _resolve_gemini,
    _Target.COPILOT: _resolve_copilot,
}


def _resolve(target: _Target) -> _Resolution:
    return _RESOLVERS[target]()


def _render_table(resolution: _Resolution, mode: str, written: bool, source: Path) -> str:
    lines: list[str] = []
    if resolution.path is None:
        lines.append(f"nsc skill install --target {resolution.target.value}")
        lines.append("")
        assert resolution.manual_instructions is not None
        lines.append(resolution.manual_instructions)
        lines.append("")
        lines.append(f"  source SKILL.md: {source}")
        return "\n".join(lines)

    if mode == "dry-run":
        lines.append(
            f"nsc skill install --target {resolution.target.value} (dry-run) "
            "— pass --apply to install"
        )
        lines.append(f"  would write to {resolution.path}")
        lines.append(f"  source: {source}")
    elif written:
        lines.append(f"✓ installed netbox-super-cli skill at {resolution.path}")
    else:
        lines.append(f"nsc skill install --target {resolution.target.value} (no-op)")
    return "\n".join(lines)


def _render_json(resolution: _Resolution, mode: str, written: bool, source: Path) -> str:
    payload: dict[str, object] = {
        "mode": mode,
        "target": resolution.target.value,
        "source": str(source),
        "destination": str(resolution.path) if resolution.path else None,
        "manual": resolution.path is None,
    }
    if resolution.manual_instructions is not None:
        payload["instructions"] = resolution.manual_instructions
    if mode == "apply":
        payload["written"] = written
    return json.dumps(payload)


def register(app: typer.Typer) -> None:
    skill_app = typer.Typer(
        name="skill",
        help="Manage the bundled portable Skill for AI agent harnesses.",
        no_args_is_help=True,
    )

    @skill_app.command("install")
    def install_cmd(
        target: Annotated[
            _Target,
            typer.Option(
                "--target",
                "-t",
                help="Which agent harness to install the Skill into.",
                case_sensitive=False,
            ),
        ],
        apply_: Annotated[
            bool,
            typer.Option("--apply", help="Actually copy the file (default: dry-run)."),
        ] = False,
        output: Annotated[
            _OutputFormat,
            typer.Option("--output", "-o", help="table|json"),
        ] = _OutputFormat.TABLE,
    ) -> None:
        resolution = _resolve(target)
        mode = "apply" if apply_ else "dry-run"
        written = False

        with bundle_path() as source:
            if apply_ and resolution.path is not None:
                resolution.path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, resolution.path)
                written = True

            if output is _OutputFormat.JSON:
                typer.echo(_render_json(resolution, mode, written, source))
            else:
                typer.echo(_render_table(resolution, mode, written, source))

    app.add_typer(skill_app, name="skill")
