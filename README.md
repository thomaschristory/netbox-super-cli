# netbox-super-cli (`nsc`)

A Python CLI for [NetBox](https://netbox.dev/) that builds its command tree dynamically from your install's live OpenAPI schema. The same binary works against any NetBox version and exposes plugin-provided endpoints automatically — the schema, not hand-written code, defines the surface.

> **Status:** Phase 1 complete. Schema → CommandModel pipeline works end-to-end against the live NetBox OpenAPI schema. The dynamic CLI tree, profiles, writes, and the rest of v1 land in Phases 2–5. Not yet on PyPI. See `docs/superpowers/specs/2026-04-30-netbox-super-cli-design.md` for the design and `docs/superpowers/plans/` for per-phase plans.

## Why

- **Plugins just work.** If your install has plugins, their endpoints appear as commands automatically.
- **Multi-instance.** Named profiles per NetBox instance.
- **Safe by default.** Writes and deletes preview as dry-runs unless you pass `--apply`.
- **AI-agent friendly.** Deterministic command shape, machine-readable output, self-describing CLI.

## Install (preview)

```
uv tool install netbox-super-cli
```

Not on PyPI yet; install from source:
```
git clone https://github.com/thomaschristory/netbox-super-cli
cd netbox-super-cli
uv sync
uv run nsc --version
```

## Try it (Phase 1)

```
# Dump every endpoint in the bundled NetBox schema as JSON
uv run nsc commands --schema nsc/schemas/bundled/netbox-4.6.0-beta2.json.gz --output json | head

# Or against a live install
uv run nsc commands --schema https://netbox.example.com/api/schema/?format=json --output json
```

## License

Apache 2.0.
