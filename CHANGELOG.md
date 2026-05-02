# Changelog

All notable changes to netbox-super-cli are tracked here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) loosely; phase milestones are pinned by git tags rather than semver bumps in `pyproject.toml` (which stays at `0.0.1` while the project is pre-1.0).

## Unreleased

### Refactor

- **Shared `SENSITIVE_HEADERS`.** Lifted the redacted-header set from `nsc/http/audit.py` and `nsc/cli/writes/apply.py` into `nsc/output/headers.py`. Output shapes preserved: audit writes `<redacted>`; apply keeps the special-case `Authorization → Token <redacted>`.
- **Shared `TRUTHY` / `FALSY` / `BOOL_STRINGS`.** Lifted from `nsc/cli/writes/{preflight,apply}.py` into `nsc/cli/writes/coercion.py` so preflight and apply can no longer drift on boolean-string acceptance.
- **`CLIOverrides.schema` renamed to `schema_override`.** Eliminates Pydantic's parent-method-shadowing `UserWarning` (`BaseModel.schema()` was the v1 name). The `--schema` CLI flag is unchanged.

## v0.3.0-phase3 — Phase 3 — live-NetBox e2e CI · 2026-05-02

Final sub-phase of Phase 3. Proves the entire 3a → 3c safety story end-to-end against a real NetBox 4.5.9 container in CI. Two latent CLI bugs surfaced and were fixed along the way (env-var-only profile sentinel; apply-path audit `record_indices`).

### Added

- `tests/e2e/` — out-of-process e2e suite invoking `python -m nsc ...` via `subprocess.run`. Six tests cover the full lifecycle (list/create/delete + dry-run + `--strict`), bulk vs loop fan-out (with audit-log `record_indices` correlation), preflight short-circuit, server-side validation, and auth failure.
- `tests/e2e/docker-compose.yml` — `netboxcommunity/netbox:v4.5.9` + Postgres 16 + Redis 7, bound to `127.0.0.1:8080`.
- `tests/e2e/wait_for_netbox.sh` — two-phase readiness probe: poll `/login/` until Django is up, then install a deterministic v1 admin API token via `docker exec ... manage.py shell`. NetBox 4.5+'s default v2-token bootstrap can't be pinned to a known plaintext, so the v1 install is the workaround; `tests/e2e/README.md` documents the rationale and the conditions that would justify revisiting (deterministic v2 bootstrap upstream, or `nsc` learning Bearer auth).
- `.github/workflows/e2e.yml` — runs on `main` pushes and on PRs that touch the write path (path-filtered per spec §8.4).
- `just e2e` — local recipe that brings the stack up, runs the suite, and tears it down even on failure.
- `tests/e2e/README.md` — local-run instructions, iteration tips, fixture token rationale.

### Changed

- `pyproject.toml`: `tests/e2e/` excluded from default pytest collection (`addopts += --ignore=tests/e2e`); the suite is opt-in via `NSC_E2E=1` (set automatically by `just e2e` and the `e2e` workflow).

### Fixed

- **`nsc/cli/runtime.py`: `<adhoc>` profile sentinel renamed to `adhoc`.** The angle-bracketed value was rejected by `nsc.cache.store._PROFILE_RE` (the cache directory-name validator), so every env-var-only invocation crashed the moment the schema cache was touched. None of the unit/respx tests caught it because they all configure a named profile via `Config`. Added a focused regression test asserting the sentinel passes the cache regex.
- **`nsc/http/client.py`, `nsc/cli/handlers.py`: apply-path audit log carries `record_indices`.** `NetBoxClient._record_attempt` was hard-coding `record_indices=[]` regardless of the routing decision, violating Phase 3a §4.3 and rendering the bulk vs loop distinction invisible in `audit.jsonl`. Added a `record_indices` kwarg threaded through `post`/`patch`/`put`/`delete` and `_send_with_retry`, populated from `ResolvedRequest.record_indices` in `_send_one`.

## v0.3.0c — Phase 3c — bulk and loop · 2026-05-02

Bulk-endpoint detection, `--bulk` / `--no-bulk` override, sequential loop fallback, and `--on-error stop|continue` with partial-progress summary envelopes.

### Added

- `nsc/cli/writes/bulk.py` — `detect_bulk_capability(operation)`, `route_to_bulk_or_loop(...)`, `run_loop(...)`. Pure logic, framework-free, fully unit-testable via injected `send_one` / `audit_attempt` / `to_envelope` callables.
- Write flags: `--bulk` (force list-shaped POST), `--no-bulk` (force per-record loop), `--on-error stop|continue` (default `stop`).
- `nsc/output/errors.py`: `ERROR_TYPE_PRECEDENCE` (stable agent contract), `worst_error_type(types)`, `summary_envelope(...)` for the partial-progress envelope on `--on-error stop` and `continue`.
- `ExplainTrace.bulk_reasoning` populated on every write trace from `RoutingDecision.reasoning`.

### Changed

- 50-record `-f` import on a bulk-capable endpoint takes one HTTP call; on a non-bulk endpoint, sequential loop.
- `apply.resolve(mode=...)` fans out to one bulk request (list body, `record_indices=[0..N)`) or N loop requests (object body, `record_indices=[i]`).
- On `--on-error stop` (default), first failure aborts; envelope carries `details.partial_progress = {success: K, failed: 1, remaining: M}` and `record_index = K`.
- On `--on-error continue`, every record is attempted; final exit code is the worst error type by precedence (`internal > transport > server > validation > conflict > rate_limited > not_found > auth > client > schema > config`); failures listed under `details.failures` with their record indices.
- `--bulk` on a non-bulk-capable endpoint → `client` error (exit 6).
- `--bulk` + `--no-bulk` together → `client` error (exit 6).

### Removed

- The 3b list-shaped `-f` rejection (`refuse_list_input_in_3b`). `-f` now accepts both single objects and arrays of objects.

### Fixed

- `run_loop` re-raises `KeyboardInterrupt` and `SystemExit` instead of classifying them as per-record failures.

## v0.3.0b — Phase 3b — single-record writes · 2026-05-01

POST/PATCH/PUT/DELETE for every endpoint in the schema becomes a Typer command; `-f` / `--field` work end-to-end with dry-run, `--apply`, `--explain`, and best-effort preflight.

### Added

- `nsc/cli/writes/{input,preflight,apply,confirmation}.py` — write pipeline stages.
- Write handlers `handle_create`, `handle_update`, `handle_delete`, `handle_custom_action_write` orchestrating the pipeline + audit + explain.
- Write flags: `--apply` / `-a`, `--explain`, `--strict`, `-f` / `--file`, `--field` (repeatable, dotted paths), `--format`.
- `ExplainTrace` populated and rendered to JSON or Rich without divergence.
- Audit log appends on every write attempt (dry-run and apply); `last-request.json` overwritten only on `--apply`.

### Fixed

- `oneOf` / `anyOf` `$ref` branches in request bodies now resolve before classification (NetBox's `oneOf:[$ref:Writable*Request, array]` shape now correctly classifies as `object_or_array`).

## v0.3.0a — Phase 3a — Foundations · 2026-05-01

Cross-cutting infrastructure for the write pipeline. No new commands; reads still work as before.

### Added

- `nsc/output/errors.py` — `ErrorEnvelope`, `ErrorType` (StrEnum), `EXIT_CODES` mapping (the agent contract).
- `nsc/output/explain.py` — `ExplainTrace`, `FieldDecision` types (wiring deferred to 3b).
- `nsc/http/audit.py` — `last-request.json` (atomic write) and `audit.jsonl` (append-only, rotated at 10 MB).
- Per-method retry policy in `nsc/http/client.py`; classified errors flow into typed envelopes.
- Top-level handler in `nsc/cli/runtime.py` converts uncaught exceptions to `internal` envelopes.
- `RequestBodyShape` on `Operation` (framework-free Pydantic model summarizing top-level type, required list, per-field primitive type and enum).

### Changed

- Read errors emit `ErrorEnvelope` with stable JSON shape; exit codes match the §4.2.2 contract.
- Retry policy: GET 5xx retried 3×; GET connect retried 3×.

## v0.2.0-phase2 — Phase 2 · 2026-05-01

Read pipeline with output rendering and column resolution.

## v0.1.0-phase1 — Phase 1 · 2026-04-30

Initial scaffold: schema parsing, command-model build, dynamic Typer registration for read-only endpoints.
