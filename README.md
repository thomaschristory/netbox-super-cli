# netbox-super-cli (`nsc`)

A Python CLI for [NetBox](https://netbox.dev/) that builds its command tree dynamically from your install's live OpenAPI schema. The same binary works against any NetBox version and exposes plugin-provided endpoints automatically — the schema, not hand-written code, defines the surface.

> **Status:** Phase 3 complete (`v0.3.0-phase3`). The full read + safe-write surface is shipped: dynamic command tree, dry-run-by-default writes with `--apply` to commit, `--explain` for resolved-request introspection, bulk-endpoint detection with loop fallback, stable error envelopes with locked exit codes, append-only audit log, and a live-NetBox e2e suite running in CI against `netboxcommunity/netbox:v4.5.9`. Not yet on PyPI.

## Why

- **Plugins just work.** If your install has plugins, their endpoints appear as commands automatically.
- **Multi-instance.** Named profiles per NetBox instance, plus env-var overrides.
- **Safe by default.** POST/PATCH/PUT/DELETE preview as dry-runs unless you pass `--apply`.
- **Agent-friendly.** Deterministic command shape, machine-readable JSON output, stable error envelope with documented exit codes.

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

## Reading

```sh
export NSC_URL=https://netbox.example.com
export NSC_TOKEN=$(cat ~/.netbox-token)

uv run nsc dcim devices list
uv run nsc dcim devices list --site-id 42 --status active --all --output json
uv run nsc dcim devices get 7
uv run nsc circuits providers list --output csv
uv run nsc ipam prefixes list --filter created__gte=2026-01-01 --output yaml
```

## Writing

```sh
# Dry-run by default — shows the resolved request without sending it.
uv run nsc dcim devices create -f device.yaml --explain

# Commit with --apply.
uv run nsc dcim devices create -f device.yaml --apply

# Bulk create: one HTTP call when the schema supports it, sequential loop otherwise.
uv run nsc dcim devices create -f devices.yaml --apply
uv run nsc dcim devices create -f devices.yaml --no-bulk --on-error continue --apply

# NDJSON / JSONL — one record per line; parse failures abort the whole batch
# before any wire request fires (`type: input_error`, exit 4, `details.bad_lines`).
uv run nsc dcim devices create -f devices.ndjson --apply
cat devices.ndjson | uv run nsc dcim devices create -f - --apply

# Per-field overrides (CLI wins over file on overlap).
uv run nsc dcim devices update 42 --field status=active --apply

# Delete; default is exit-0 if already gone, --strict turns missing-id into exit 9.
uv run nsc dcim devices delete 42 --apply
uv run nsc dcim devices delete 42 --apply --strict
```

Every write attempt — dry-run included — appends one line to `~/.nsc/logs/audit.jsonl`; the most recent exchange is also mirrored to `~/.nsc/logs/last-request.json`.

### Bulk input formats

| Form | File extension or stdin shape | Routing |
|------|-------------------------------|---------|
| YAML mapping | `.yaml` / `.yml` | Single record. |
| YAML list | `.yaml` / `.yml` | Bulk: one record per list item. |
| JSON object | `.json` or `{...}EOF` on stdin | Single record. |
| JSON array | `.json` or `[...]` on stdin | Bulk: one record per array item. |
| **NDJSON** | **`.ndjson` / `.jsonl` or `{...}\n{...}` on stdin** | **Bulk: one record per line.** |

Stdin is sniffed from the first 512 bytes (first non-whitespace byte plus a one-object lookahead for newline-then-`{`). NDJSON parse failures collect up to 20 `bad_lines` and abort before any wire request; `--no-bulk` still forces a loop fallback for any bulk shape.

### Audit log sensitivity

`audit.jsonl` is **confidential** (not secret). It records what was sent — record-level data your account had write access to. The CLI redacts:

- HTTP headers in the `SENSITIVE_HEADERS` set (e.g. `Authorization`, `X-API-Key`) — replaced with `"<redacted>"`.
- Request-body fields whose OpenAPI definition has `format: password` OR whose name (case-insensitive) is one of: `password`, `secret`, `token`, `api_key`, `apikey`, `private_key`, `passphrase`, `client_secret`. Nested fields and arrays of objects are walked recursively.

The wire body sent to NetBox is **not** redacted — only the audit log. A failed write still records the redacted body; redaction is irreversible. Treat `audit.jsonl` like a verbose application log: gate it behind your home-directory permissions and rotate / archive accordingly. A "redact everything" mode is deferred to Phase 5+.

## Output and errors

- `--output {table,json,yaml,csv,jsonl}`. Table is the default on a TTY; JSON is the default when stdout is piped.
- On `--output json`, the records array is emitted directly (no NetBox-style `count`/`results` wrapper); single-record writes emit the resulting record dict.
- Failures emit a stable `ErrorEnvelope` (JSON to stdout on `--output json`, Rich panel to stderr otherwise) with `type ∈ {auth, not_found, validation, conflict, rate_limited, server, transport, schema, config, client, internal, ambiguous_alias, unknown_alias, input_error}` and a documented exit code per type. See `CHANGELOG.md` and the spec for the full table.

## Schema introspection

```sh
# Dump every endpoint in the bundled NetBox schema as JSON.
uv run nsc commands --schema nsc/schemas/bundled/netbox-4.6.0-beta2.json.gz --output json | head

# Or against a live install.
uv run nsc commands --schema https://netbox.example.com/api/schema/?format=json --output json
```

## License

Apache 2.0.
