# Working on netbox-super-cli (for AI agents)

This is the contributor guide for AI agents (and humans!) modifying this repo. The end-user-facing AI guide is the bundled Skill at `skills/netbox-super-cli/SKILL.md`.

## Architecture cheat sheet

- `nsc/schema/` — parses an OpenAPI document into Pydantic models. Knows nothing about CLIs.
- `nsc/model/` — the normalized command tree (data only, framework-free). The "brain".
- `nsc/builder/` — converts a parsed schema into a `CommandModel`.
- `nsc/cli/` — the Typer app; consumes a `CommandModel`.
- `nsc/http/` — thin httpx wrapper: auth, retries, audit log.
- `nsc/output/` — formatters (table/json/jsonl/yaml/csv) + error envelope.
- `nsc/config/` — config loader + Pydantic models + ruamel.yaml round-trip writer.
- `nsc/cache/` — disk cache for generated command-models.
- `nsc/auth/` — login verification helpers (pre-flight probes, token rotate).
- `nsc/aliases/` — curated alias resolver (`ls`, `get`, `rm`, `search`). Framework-free.
- `nsc/skill/` — bundle-path helper for the portable `SKILL.md` shipped in the wheel.
- `nsc/schemas/bundled/` — versioned NetBox OpenAPI snapshots, fallback when offline.

The hard rule: **`nsc/model/` imports nothing from `nsc/cli/`, `nsc/http/`, or any framework.** If you need to add a dependency to `model/`, you're probably solving the wrong problem.

## Common commands

- `just sync` — install/refresh deps.
- `just test` — run all tests.
- `just lint` — ruff + mypy --strict.
- `just fix` — auto-fix ruff issues.
- `just nsc <args>` — run the local CLI.

## Conventions

- Python 3.12+, full type annotations, `mypy --strict`.
- Pydantic v2 for all structured data.
- Conventional Commits.
- TDD: write the failing test first.
- No comments on what code does; only on non-obvious *why*.

## Branching

`main` is protected — direct pushes are rejected. All work happens on
short-lived feature branches (`fix/<slug>`, `feat/<slug>`, `docs/<slug>`,
…), opens a PR against `main`, passes required CI checks, and squash-merges.
Releases are *tags* on `main`, not branches. Full convention:
[`docs/contributing/branching.md`](docs/contributing/branching.md).

## Where the design lives

- `docs/superpowers/specs/2026-04-30-netbox-super-cli-design.md` — the full design.
- `docs/superpowers/plans/` — implementation plans, one per phase.
