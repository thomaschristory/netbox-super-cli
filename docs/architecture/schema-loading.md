# Schema loading

`nsc/schema/` fetches and parses the OpenAPI document.

## Resolution order

Highest priority first, given the active `defaults.schema_refresh` policy
and an optional `--refresh-schema` override:

1. `--schema <path-or-url>` — one-shot override. Always wins; never
   consults the TTL fast-path or the network.
2. **TTL fast-path.** If the policy is `daily`, `weekly`, or `manual` and
   the newest sidecar-validated cache entry for the active profile is
   fresher than the policy's TTL, `nsc` returns it directly with no HTTP
   round-trip. Skipped when `--refresh-schema` is passed (or the policy
   is `on-hash-change`).
3. Live fetch from the active profile's `schema_url` (explicit) or
   `{profile.url}/api/schema/?format=json`. The fetched body is hashed;
   if a cache file already exists at that hash it's loaded directly,
   otherwise the command-model is rebuilt and saved.
4. On fetch failure: any cached entry for the profile (warns once on
   stderr).
5. Bundled snapshot at `nsc/schemas/bundled/netbox-<closest-version>.json`
   (shipped in the wheel) — last-resort offline fallback.

## Hashing

The cache key is `sha256` of the canonicalized schema body (JSON
re-serialized with sorted keys, no whitespace). Cosmetic changes to the
upstream schema (whitespace, key order) don't bust the cache, but any
semantic change (new endpoint, changed field) does.

## Cache layout

Each profile has a directory under `~/.nsc/cache/<profile>/` containing,
per schema hash:

- `<hash>.json` — the generated `CommandModel`. Loaded via
  `CacheStore.load`, which re-verifies that the file's embedded
  `schema_hash` matches the filename — so a tampered or copied JSON
  file is rejected.
- `<hash>.meta.json` — a sidecar with `{"fetched_at": <epoch_seconds>}`.
  Drives the TTL fast-path. Written atomically alongside the cache file
  via temp-file + `os.replace`.

A sidecar dated more than 60s in the future (clock skew or tampering)
is rejected. A cache entry without its sidecar is treated as stale —
that's the upgrade path for caches written before sidecars existed.

## Offline behavior

- Live schema unreachable + cache present → use cache, warn once on
  stderr.
- Live schema unreachable + no cache → fall back to the closest bundled
  version, warn loudly.
- All such errors include a remediation hint pointing at
  `--refresh-schema` for once the instance is reachable again.

## Refresh modes

In `~/.nsc/config.yaml`:

```yaml
defaults:
  schema_refresh: daily   # default since the v1.0.2 release line
```

| Value            | TTL    | Behaviour                                                       |
|------------------|--------|-----------------------------------------------------------------|
| `daily`          | 24h    | Default. Trust a fresh cache; re-fetch once a day.              |
| `weekly`         | 7d     | Trust longer; suitable for stable NetBox deployments.           |
| `manual`         | ∞      | Never auto-invalidate. Use `--refresh-schema` to update.        |
| `on-hash-change` | 0      | v1.0.1 behaviour: re-fetch every invocation, compare hashes.    |

Use `nsc --refresh-schema <subcommand>` to force a one-shot refresh
that bypasses the TTL fast-path under any policy.

## When you change NetBox versions

The hash changes → next invocation that bypasses the fast-path
regenerates the model. Under `daily` (the default) you may need to
prepend `--refresh-schema` to your first post-upgrade invocation, or
wait up to 24h. The old `<old_hash>.json` (and its sidecar) become
orphaned and get cleaned by `nsc cache prune`.
