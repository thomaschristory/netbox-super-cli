# Caching

`~/.nsc/` holds all on-disk state. Bundled schemas live inside the installed
wheel and are NOT copied into `~/.nsc/`.

## Layout

```
~/.nsc/
├── config.yaml
├── cache/
│   ├── prod/<schema-hash>.json    # generated CommandModel
│   ├── lab/<schema-hash>.json
│   └── adhoc/<schema-hash>.json   # env-var-only invocations
└── logs/
    ├── nsc.log                     # rotated, 7 days
    ├── last-request.json           # most recent HTTP exchange
    └── audit.jsonl                 # append-only mutation log
```

## Invalidation

The cache is keyed by `sha256` of the canonicalized schema body. When the live
schema's hash differs from the cached one, `nsc` regenerates and emits a
one-line "schema changed, regenerating…" notice on stderr.

## Cleaning up

`nsc cache prune` handles three classes of orphan:

1. Profile directories not in `~/.nsc/config.yaml` (e.g., a removed profile).
2. `<schema_hash>.json` files inside an active profile whose hash no longer
   matches the live schema. **Skipped per-profile when the profile is
   offline** so a network blip never removes the offline fallback.
3. With `--max-age <days>`: cache files older than the threshold (excludes
   files already covered by rule 1).

The `adhoc` cache is **never pruned automatically** — it represents valid
env-var-only usage.

```sh
nsc cache prune                      # dry-run
nsc cache prune --apply              # actually delete
nsc cache prune --max-age 30 --apply
nsc cache prune --output json        # structured envelope
```
