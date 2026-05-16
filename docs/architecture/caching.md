# Caching

`~/.nsc/` holds all on-disk state. Bundled schemas live inside the installed
wheel and are NOT copied into `~/.nsc/`.

## Layout

```
~/.nsc/
├── config.yaml
├── cache/
│   ├── prod/<schema-hash>.json         # generated CommandModel
│   ├── prod/<schema-hash>.meta.json    # sidecar: {"fetched_at": <epoch>}
│   ├── lab/<schema-hash>.json
│   └── adhoc/<schema-hash>.json        # env-var-only invocations
└── logs/
    ├── last-request.json               # most recent HTTP exchange (overwritten)
    └── audit.jsonl                     # append-only mutation log
                                        #   (rotated to audit.jsonl.1 at 10 MB)
```

The location root is `~/.nsc/` unless `NSC_HOME` is set, in which case it is
`$NSC_HOME` (expanded and resolved).

## Invalidation

The cache is keyed by `sha256` of the canonicalized schema body. There are two
distinct caches: this **command-model disk cache** (`<hash>.json`), and the
**schema-source TTL fast-path** that decides whether to re-fetch the live
schema at all.

Invalidation is **TTL-gated**, not "every invocation". Under the default
`daily` policy (`Defaults.schema_refresh = SchemaRefresh.DAILY`) `nsc` trusts
the cached command-model — and skips the schema fetch entirely — as long as the
profile's newest `<hash>.meta.json` sidecar `fetched_at` is within the policy's
TTL. Only once the TTL has lapsed (or the policy forces it) does `nsc` re-fetch
the live schema; a changed schema then produces a new hash and a new
`<hash>.json`. Freshness is keyed off the sidecar's `fetched_at`, **not** the
cache file's mtime, so a `touch`, backup-restore, or `cp -p` cannot fake
freshness. A sidecar dated more than 60s in the future (clock skew or
tampering) is rejected.

When a live fetch returns a hash that is already cached, the sidecar's
`fetched_at` is bumped (`CacheStore.touch_fetched_at`) so the TTL fast-path
trusts the cache on the next invocation — this also self-heals legacy caches
written before sidecars existed.

Force a re-fetch sooner with the global `--refresh-schema` flag (bypasses the
TTL fast-path under any policy) or `nsc login --fetch-schema`. The full policy
table lives in [Schema loading](schema-loading.md#refresh-modes).

## Cleaning up

`nsc cache prune` handles three classes of orphan:

1. Profile directories not in `~/.nsc/config.yaml` (e.g., a removed profile).
2. `<schema_hash>.json` files inside an active profile whose hash no longer
   matches the live schema. **Skipped per-profile when the profile is
   offline** so a network blip never removes the offline fallback.
3. With `--max-age <days>`: cache files older than the threshold (excludes
   files already covered by rule 1).

The `adhoc` cache is **never pruned automatically** — it represents valid
env-var-only usage. Applying a prune also removes each deleted file's
`<hash>.meta.json` sidecar.

```sh
nsc cache prune                      # dry-run
nsc cache prune --apply              # actually delete
nsc cache prune --max-age 30 --apply
nsc cache prune --output json        # structured envelope
```
