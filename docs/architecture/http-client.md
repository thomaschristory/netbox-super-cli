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
- `request.headers` (sensitive headers, incl. `Authorization`, rewritten
  to `"<redacted>"` — the key stays, the value is masked)
- `request.query`, `request.body` (sensitive `sensitive_paths` fields
  rewritten to `"<redacted>"`); bodies over 256 KB collapse to
  `{"_truncated": true, "_size_bytes": N}` with `request.body_truncated`
- `response.status_code`, `response.headers`, `response.body` (same
  256 KB truncation via `response.body_truncated`); `response` is `null`
  on a transport failure
- `duration_ms`, `attempt_n`, `final_attempt`, `error_kind`
- `dry_run`, `preflight_blocked`, `record_indices`, `applied`, `explain`

The audit file is append-only and rotates to `audit.jsonl.1` at 10 MB;
failed writes do NOT unredact. See
[Writes and safety](../guides/writes-and-safety.md) for the full redaction
contract.

## What it deliberately does not do

- Async — sync only in v1, kept feasible by httpx if a future async path lands.
- Connection pooling across profiles — each profile gets its own `Client`.
- Caching responses — caching the command-model is enough; caching response
  payloads would surprise users.
