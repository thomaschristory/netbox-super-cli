# HTTP client

`nsc/http/` is a thin wrapper around `httpx.Client`.

## What it adds

- Token auth: `Authorization: Token <token>` header (plus
  `Accept: application/json`), set once per Client.
- Configurable `verify_ssl` and `timeout` (default 30s, from
  `Defaults.timeout`).
- Method-aware retries, up to 3 attempts with exponential backoff
  (`base_delay` 0.5s, ±25% jitter):
    - **Reads** (GET/HEAD/OPTIONS) retry on 5xx **and** on connect
      failures.
    - **Writes** (POST/PATCH/PUT/DELETE) retry **only** on a provable
      connect failure (request never left the client). They are
      **never** retried on 5xx, read-timeout, or ambiguous transport
      errors — a write that may have reached the server is not replayed.
  Every attempt is recorded as its own audit entry with `attempt_n` and
  `final_attempt`; redaction is applied on every write, so a failed
  retry never unredacts.
- Pagination helper that follows `next` URLs (used by `--all`).
- Audit log appender at `~/.nsc/logs/audit.jsonl` — written for writes
  always, and for any request when `--debug` is set.

## Concurrency (`--workers N`)

Bulk write commands accept `--workers N` (default 1, max 32) to keep up to N
requests in flight. Concurrency is **thread-based**: a `ThreadPoolExecutor`
fans the per-record loop out over the single sync `httpx.Client` — there is no
async path. Per-record `--on-error` semantics are preserved regardless of
worker count. Audit appends are serialized by a module-level lock
(`_APPEND_LOCK` in `nsc/http/audit.py`) wrapped around the whole
open/write/close, so concurrent workers can never interleave a partial line —
each record is one well-formed JSON line.
- A "last request" snapshot at `~/.nsc/logs/last-request.json`
  (overwritten every call, regardless of `--debug`) — handy for triage.

## Auth and the bootstrap path

A schema fetch may run before the first command request (only when the
TTL fast-path misses — see [Caching](caching.md)); it uses its own
short-lived `httpx.Client` in `nsc/schema/`, not this `NetBoxClient`.
Command requests then go through a single `NetBoxClient` whose
`httpx.Client` carries the auth header for the life of the process.
Token rotation via `nsc login --rotate` does NOT invalidate the cached
model (the schema hash is what keys the cache; the token never affected
it).

## Audit entry shape

Each line of `audit.jsonl` is a JSON object with:

- `schema_version`, `timestamp` (UTC ISO8601, `…Z`)
- `operation_id`, `method`, `url`
- `request.headers` (sensitive headers — `Authorization`, `Cookie`,
  `Set-Cookie`, `X-API-Key`, `Proxy-Authorization` — rewritten to
  `"<redacted>"`; the key stays, the value is masked)
- `request.query`, `request.body` (sensitive `sensitive_paths` fields
  rewritten to `"<redacted>"`); bodies over 256 KB collapse to
  `{"_truncated": true, "_size_bytes": N}` with `request.body_truncated`
- `response.status_code`, `response.headers` (redacted with the same
  sensitive-header set as the request side), `response.body` (same
  256 KB truncation via `response.body_truncated`); `response` is `null`
  on a transport failure
- `duration_ms`, `attempt_n`, `final_attempt`, `error_kind`
- `dry_run`, `preflight_blocked`, `record_indices`, `applied`, `explain`

## Redaction modes

Redaction is applied when each entry is serialized (`nsc/http/audit.py`), so a
failed retry never unredacts. The `defaults.audit_redaction` config setting
selects the mode:

- `safe` (default) — the full audit shape above, with sensitive headers and
  `sensitive_paths` body fields masked to `"<redacted>"` and bodies over 256 KB
  truncated.
- `full` — compliance escalation that drops every body, header, and query
  string entirely. Each line keeps exactly five keys —
  `{method, url, status_code, timestamp, profile}` — and `url` is sanitized to
  scheme + host[:port] + path so neither query params nor `user:pass@` userinfo
  can leak through the one remaining string field.

The audit file is append-only and rotates to `audit.jsonl.1` at 10 MB; it is
created owner-only (`0600`) inside a `0700` logs directory, and failed writes do
NOT unredact. The state root (`~/.nsc`) and its subdirectories are clamped to
`0700` via a shared `ensure_private_dir()` (`nsc/config/settings.py`) used by
both the config writer and the audit-dir code. See
[Writes and safety](../guides/writes-and-safety.md) for the full redaction
contract.

## What it deliberately does not do

- Async — sync only in v1, kept feasible by httpx if a future async path lands.
- Connection pooling across profiles — each profile gets its own `Client`.
- Caching responses — caching the command-model is enough; caching response
  payloads would surprise users.
