# Architecture overview

`nsc` is composed of five layers. The "brain" — schema parsing and the normalized
command-model — knows nothing about Typer, Rich, or httpx. The CLI layer
consumes the brain; a future TUI could too without changing the brain.

```
nsc/
├── schema/    # OpenAPI fetching, hashing, parsing
├── model/     # Normalized command-model (data only, framework-free)
├── builder/   # Schema → CommandModel
├── cli/       # Typer application; walks the model, registers commands
├── http/      # Thin httpx wrapper: auth, retries, audit
├── output/    # Formatters (table/json/jsonl/yaml/csv) + error envelope
├── config/    # Pydantic config models + ruamel.yaml writer
├── cache/     # On-disk cache for generated CommandModels
├── auth/      # Login verification helpers
└── aliases/   # Curated alias resolver (ls/get/rm/search)
```

## The hard rule

`nsc/model/` imports nothing from `nsc/cli/`, `nsc/http/`, or any framework.
If you need to add a dependency to `model/`, you're solving the wrong problem.

## Data flow at runtime

1. `nsc` startup → resolve profile (CLI flags > env > config > adhoc).
2. Resolve schema source (live URL > cache > bundled fallback).
3. Hash + parse → build the command-model (or load cached).
4. Hand model to Typer; register commands dynamically.
5. Dispatch.
6. `http/` executes (or shows dry-run).
7. `output/` renders.

## Where to read next

- [Schema loading](schema-loading.md) — fetch, hash, fallback chain.
- [Command generation](command-generation.md) — how `operationId` becomes a verb.
- [HTTP client](http-client.md) — auth, retries, audit log.
- [Caching](caching.md) — disk layout, invalidation.

For the full design rationale, see the specs in `docs/superpowers/specs/` (in
the repo, not in this site — the planning artifacts are local-only).
