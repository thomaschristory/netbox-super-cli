# Changelog

All notable changes to netbox-super-cli are tracked here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) loosely; phase milestones are pinned by git tags rather than semver bumps in `pyproject.toml` (which stays at `0.0.1` while the project is pre-1.0).

## Unreleased

## v0.4.0c — Phase 4c — Curated aliases · 2026-05-03

Third sub-phase of Phase 4. Ships the four curated alias verbs (`nsc ls`, `nsc get`, `nsc rm`, `nsc search`) on top of the dynamic command tree, with byte-identical audit lines so downstream consumers cannot tell aliases apart from their full-path equivalents.

### Added

- `nsc ls <resource>` — list a resource by plural name. Term resolved via `nsc/aliases/resolve()` against the in-memory `CommandModel`; case-insensitive equality; plural-only (singular forms emit `unknown_alias`). Delegates to the same `handle_list` the dynamic tree uses.
- `nsc get <resource> <id|name>` — get one record. Numeric → path-param `id`; non-numeric → list-filter on `name`, error on 0 or ≥2 matches, otherwise call `handle_get` with the resolved id. The dereference list call is a GET and writes no audit entry (consistent with the Phase 3 contract that audit logs only POST/PATCH/PUT/DELETE).
- `nsc rm <resource> <id|name> --apply` — delete one record. Same id/name dispatch as `get`, plus the `--apply` gating from `handle_delete` (dry-run by default). Wire shape and audit shape are byte-identical to `nsc <tag> <resource> delete <id> --apply` (modulo `timestamp`, `duration_ms`, `attempt_n`).
- `nsc search <query>` — query `/api/search/?q=<query>` if the schema exposes it. NetBox 4.5+ does; older builds fall through to `unknown_alias` with `details.reason="search_endpoint_unavailable"`.
- `nsc/aliases/` — new framework-free top-level package. Imports nothing from `nsc/cli`, `nsc/http`, Typer, Rich. Public surface: `AliasVerb`, `ResolvedAlias`, `AmbiguousAlias`, `UnknownAlias`, `resolve()`. Verb-required-op gating (e.g., `rm` ignores resources that lack `delete_op`) happens before ambiguity classification.
- `ErrorType.AMBIGUOUS_ALIAS` (exit 13) and `ErrorType.UNKNOWN_ALIAS` (exit 14) plus `ambiguous_alias_envelope()` and `unknown_alias_envelope()` helpers in `nsc/output/errors.py`. Existing exit codes 1, 3–12 are unchanged.

### Changed

- `nsc/builder/build.py` — `_resource_from_path` now accepts 2-segment API paths (`/api/search/`, `/api/status/`, `/api/schema/`, `/api/authentication-check/`). Each becomes `model.tags[<name>].resources[<name>]` with a single `list_op`. Previously these were silently dropped, which made `/api/search/` unreachable from the resolver.
- `nsc/cli/app.py` — `_BootstrappingGroup.make_context` now resets `app.registered_groups` and the Click group's `commands` dict back to the static-commands baseline at the start of every invocation. Without this, dynamic-tree groups accumulated across CliRunner calls in the same process, leaking command state between tests (and, in principle, between invocations of any long-running CLI host).

### Notes

- The audit-identity contract is verified at two levels: a unit test (`tests/cli/test_aliases_commands.py::test_alias_rm_audit_line_byte_equivalent_to_full_path_delete`) using respx, and an e2e step (`tests/e2e/test_full_cycle.py`) creating a parallel tag deleted via the dynamic-tree path and asserting the alias-delete and full-path-delete audit lines match modulo `{timestamp, duration_ms, attempt_n, response, url, record_indices, request}`. The first set is unconditionally volatile; the latter three differ because the parallel tag has a different id.
- v1 plural-only stance preserved: `nsc ls device` (singular) emits `unknown_alias`, NOT a guess at `devices`. Singular forms may be added in a future phase.
- NDJSON input + body-aware audit redaction land in 4d (final).
- Test counts: 475 unit tests passing (up from 436 at v0.4.0b: 9 new error-type tests, 12 new resolver tests, 14 new alias-command tests, 2 new builder tests, plus 2 unit-test adjustments); 1 e2e test extended (`test_full_cycle.py`).
- Cold-start benchmark: median 260 ms (well under the 300 ms target; the bench script's stricter 250 ms internal threshold is a soft signal, not a regression).

## v0.4.0b — Phase 4b — Onboarding verbs · 2026-05-03

Second sub-phase of Phase 4. Ships the onboarding surface (`nsc init`, `nsc login`, `nsc profiles`) on top of the 4a writer, finishes the migration off `pyyaml`, and adds the first e2e coverage for `login` against live NetBox.

### Added

- `nsc init` — first-run wizard. Prompts for profile name, NetBox URL, and token storage mode (plaintext or `!env VARNAME`), then writes a minimal `~/.nsc/config.yaml` via the 4a round-trip writer. Refuses to clobber an existing non-empty config (and a malformed-but-present config is treated as non-empty — refuse, don't overwrite). Offline-safe: `init` does not call `verify()`.
- `nsc login` — verify / `--new` / `--rotate` (mutually exclusive). Bare `nsc login` (or `--profile <name>`) verifies the named profile against `GET /api/status/` and `GET /api/users/me/`. `--new --profile <name> --url <url>` creates and verifies a new profile (refuses if it exists). `--rotate --profile <name>` prompts for a new token, verifies it, then replaces the stored token. Storage modes: `--store plaintext` (default) writes the raw token; `--store env --env-var NAME` writes `!env NAME`. On success prints `✓ authenticated as <user>, NetBox <ver>`. The cache is never touched by login.
- `nsc profiles list|add|remove|rename|set-default` — manage profiles non-interactively. `list` prints a table by default with `*` on the default; `--output json` (validated against a strict enum) emits `{"default": ..., "profiles": [{"name": ..., "url": ...}]}` for scripts. `add` is the non-interactive analogue of `login --new`. `remove` refuses to drop the default unless `--force` and purges the profile's cache directory on success. `rename` rebuilds the YAML mapping in place (preserving key order), updates `default_profile` if it pointed at `<old>`, and moves the cache directory. `set-default` rejects unknown names.
- `nsc/auth/verify.py` — pre-flight `verify(profile)` that issues two probes against the candidate NetBox using a fresh `httpx.Client`. Bypasses `NetBoxClient` deliberately so login attempts stay out of `audit.jsonl` and never retry. `VerifyError` carries `status_code` and `user_check_status` so callers can distinguish "wrong URL / NetBox down" from "URL fine, token rejected"; the latter shows up in the auth envelope as `details.user_check_status`.
- `CacheStore.move(old, new)` and `CacheStore.purge(profile)` — primitives for the `profiles rename`/`remove` cache hooks. Both validate profile names against `_PROFILE_RE`; `move` raises `FileExistsError` if the target is already populated.
- E2E: `tests/e2e/test_login.py` covers bare login, `--new`, `--rotate` (mints a fresh token via `POST /api/users/tokens/`, skips if the build doesn't expose token minting), and a bad-token auth-envelope scenario. Gated by `NSC_E2E=1` with the rest of the e2e suite.

### Changed

- `pyyaml` removed from `pyproject.toml` runtime and dev dependencies; `ruamel.yaml` is now the sole YAML implementation across `nsc/config/`, `nsc/output/yaml_.py`, and `nsc/cli/writes/input.py`. The output formatter and input parser use `YAML(typ="safe", pure=True)` (plain mode produces `dict`/`list`, not `CommentedMap`); the config layer continues to use round-trip mode from 4a. `types-pyyaml` dropped from dev deps and from the pre-commit mypy hook's `additional_dependencies`.
- The root callback's `ConfigParseError` fallback was extended from killing every invocation with exit 2 to letting `init`/`login`/`profiles` proceed with an empty `Config()`. Subcommands then surface their own `config_error` envelopes (or refuse-to-clobber refusals) instead of a generic parse-error message.
- Auth and config-error paths in `nsc login` (and `nsc profiles`) now route through `emit_envelope` so they honor `--output` and TTY-routing rules — matching every other command's envelope contract. The previous direct `print(render_to_json(...), file=sys.stderr)` was inconsistent with how scripted callers expect failures to render.

### Notes

- The `auth_error` envelope shape is unchanged structurally — `details` is already `dict[str, Any]`, so `details.user_check_status` is documented but not type-versioned.
- Curated aliases (`nsc ls/get/rm/search`) land in 4c. NDJSON input + body-aware audit redaction land in 4d.
- Cold-start benchmark: median ~255 ms (well under the 300 ms target; the bench script's stricter 250 ms internal threshold is a soft signal, not a regression).
- Test counts: 436 unit tests passing (up from 391 at v0.4.0a); 4 new e2e tests gated by `NSC_E2E`.

## v0.4.0a — Phase 4a — Config writer foundation · 2026-05-03

First sub-phase of Phase 4. Ships the on-disk config write surface (`nsc config get|set|unset|list|edit|path`) on top of `ruamel.yaml`'s round-trip mode. Comments, key order, and `!env` tags survive every read-modify-write cycle. No new onboarding verbs (those land in 4b).

### Added

- `nsc config get <key>`, `nsc config list`, `nsc config path` — read the on-disk config. `get` accepts a dotted path (e.g. `profiles.prod.url`) and prints scalars as plain text or subtrees as YAML; `path` prints the resolved config-file location.
- `nsc config set <key> <value>`, `nsc config unset <key>`, `nsc config edit` — round-trip-preserving edits. Hand-authored comments, key order, and `!env` tags pass through writes intact. `set` creates intermediate maps as needed and refuses to silently restructure (e.g. overwriting a map with a scalar fails fast). `unset` prunes empty parent maps. `edit` opens `$EDITOR` (or `$VISUAL`, falling back to `vi` / `nano`) on the resolved config path.
- `nsc/config/writer.py` — atomic writes via tempfile + fsync + `os.replace`, 0600 mode on newly created files. Best-effort `flock` on a sidecar `.lock` file (POSIX); degrades cleanly on platforms without `fcntl`.

### Changed

- `nsc/config/loader.py` switched from `pyyaml.SafeLoader` to `ruamel.yaml`'s `YAML(typ="rt")`. The external contract (`load_config(path) -> Config` raising `ConfigParseError`) is unchanged. Reuses a private `_round_trip_yaml()` factory shared with the writer for the parser-config baseline.

### Notes

- `pyyaml` remains in `pyproject.toml` while `nsc/output/yaml_.py` and `nsc/cli/writes/input.py` still import it. The drop is deferred to a 4b follow-up rather than widening 4a's scope.
- Onboarding verbs (`nsc init`, `nsc login`, `nsc profiles`) land in 4b. Curated aliases (`nsc ls/get/rm/search`) land in 4c. NDJSON output + audit redaction lands in 4d.
- `ruamel.yaml`'s `add_constructor` registers at the class level, which means the loader's resolving `!env` constructor leaks into any later `YAML(typ="rt")` instance unless explicitly overridden. The writer registers its own tag-preserving `!env` constructor (returning a `TaggedScalar`) on top of that to keep round-trip behavior deterministic regardless of import order.
- Cold-start benchmark: median ~280 ms (improved from Phase 3d's ~321 ms median).

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
