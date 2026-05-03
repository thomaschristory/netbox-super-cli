# Schema loading

`nsc/schema/` fetches and parses the OpenAPI document.

## Resolution order

Highest priority first:

1. `--schema <path-or-url>` — one-shot override.
2. Active profile's `schema_url` (explicit) or `{profile.url}/api/schema/?format=json`.
3. Cached generated command-model at `~/.nsc/cache/<profile>/<schema-hash>.json`
   if its hash matches the live schema.
4. Bundled snapshot at `nsc/schemas/bundled/netbox-<closest-version>.json` (in
   the wheel) — last-resort offline fallback.

## Hashing

The cache key is `sha256` of the canonicalized schema body (JSON re-serialized
with sorted keys, no whitespace). This means cosmetic changes to the upstream
schema (whitespace, key order) don't bust the cache, but any semantic change
(new endpoint, changed field) does.

## Offline behavior

- Live schema unreachable + cache present → use cache, warn once on stderr.
- Live schema unreachable + no cache → fall back to closest bundled version,
  warn loudly.
- Errors include a remediation hint ("run `nsc refresh` when the instance is
  reachable").

## Refresh modes

In `~/.nsc/config.yaml`:

```yaml
defaults:
  schema_refresh: on-hash-change   # default
```

Other values: `manual`, `daily`, `weekly`. `manual` means the cache is never
auto-invalidated — you must call `nsc refresh` explicitly.

## When you change NetBox versions

The hash changes → next invocation regenerates the model in the background.
The old `<old_hash>.json` becomes orphan and gets cleaned by `nsc cache prune`.
