# netbox-super-cli (`nsc`)

A Python CLI for [NetBox](https://netbox.dev/) that builds its command tree dynamically from your install's live OpenAPI schema. The same binary works against any NetBox version and exposes plugin-provided endpoints automatically — the schema, not hand-written code, defines the surface.

> **Status:** Phase 1 in progress. Not yet released. See `docs/superpowers/specs/2026-04-30-netbox-super-cli-design.md` for the full design.

## Why

- **Plugins just work.** If your install has plugins, their endpoints appear as commands automatically.
- **Multi-instance.** Named profiles per NetBox instance.
- **Safe by default.** Writes and deletes preview as dry-runs unless you pass `--apply`.
- **AI-agent friendly.** Deterministic command shape, machine-readable output, self-describing CLI.

## Install (preview)

```
uv tool install netbox-super-cli
```

Phase 1 isn't published yet; install from source:
```
git clone https://github.com/mick27/netbox-super-cli
cd netbox-super-cli
uv sync
uv run nsc --version
```

## License

Apache 2.0.
