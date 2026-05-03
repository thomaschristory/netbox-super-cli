# Development

Contributing to `nsc`. The full contributor guide for AI agents working on
this repo lives at `CLAUDE.md` (root of the repo); this page is the human
front door.

## Setup

```sh
git clone https://github.com/thomaschristory/netbox-super-cli
cd netbox-super-cli
uv sync                       # creates .venv with runtime + dev deps
uv sync --group docs          # add docs deps when working on the site
just hooks                    # install pre-commit
```

## Day-to-day commands

```sh
just test          # full pytest suite
just lint          # ruff + ruff format --check + mypy --strict
just fix           # auto-fix ruff issues
just bench         # cold-start benchmark (target <300ms median)
just nsc <args>    # run the local CLI (e.g., just nsc dcim devices list)
just docs          # serve the docs site at http://localhost:8000
just docs-build    # build the site, fail on broken links / missing nav
```

## Conventions

- Python ≥ 3.12, full type annotations, `mypy --strict`.
- Pydantic v2 for all structured data.
- Conventional commits.
- TDD: failing test first, then minimal code to pass.
- Comments are for non-obvious *why*, never *what*.
- `nsc/model/` stays framework-free.

## Pre-commit hooks

`ruff` + `mypy` run on every commit. **Never use `--no-verify`** — fix the
underlying issue and create a new commit. If `ruff format` modifies a file
during the hook, re-`git add` and re-commit.

## Where the design lives

- `docs/superpowers/specs/` — design specs (gitignored; local-only).
- `docs/superpowers/plans/` — implementation plans, one per sub-phase
  (gitignored).
- `CHANGELOG.md` — what shipped per tag.
