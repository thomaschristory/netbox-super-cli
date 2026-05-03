# HTTP client

`nsc/http/` is a thin wrapper around `httpx.Client`.

## What it adds

- Token auth: `Authorization: Token <token>` header, set once per Client.
- Configurable `verify_ssl` and `timeout` (default 30s).
- Retries on 5xx: 3 attempts with exponential backoff. The retry path
  preserves the audit log entry — failed retries do not unredact.
- Pagination helper that follows `next` URLs (used by `--all`).
- Audit log appender at `~/.nsc/logs/audit.jsonl`.
- A "last request" snapshot at `~/.nsc/logs/last-request.json` (overwritten
  each call) — handy for `nsc --debug` triage.

## Auth and the bootstrap path

The first request after startup is a schema fetch (unless cached). All
subsequent requests reuse the same `httpx.Client` with the auth header attached.
Token rotation via `nsc login --rotate` does NOT invalidate the cached model
(the hash of the schema is what matters; the token didn't affect that).

## Audit entry shape

Each line of `audit.jsonl` is a JSON object with:

- `timestamp` (UTC ISO8601)
- `operation_id`, `method`, `url`
- `request.body` (with sensitive fields redacted to `"<redacted>"`)
- `request.headers` (Authorization stripped before write)
- `response.status_code`, `response.body` (excerpted on large bodies)
- `dry_run: true|false`
- `attempt_n` for retries

The audit file is append-only; failed writes do NOT unredact. See
[Writes and safety](../guides/writes-and-safety.md) for the full redaction
contract.

## What it deliberately does not do

- Async — sync only in v1, kept feasible by httpx if a future async path lands.
- Connection pooling across profiles — each profile gets its own `Client`.
- Caching responses — caching the command-model is enough; caching response
  payloads would surprise users.
