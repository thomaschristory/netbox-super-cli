# Adding bundled schemas

The bundled schemas at `nsc/schemas/bundled/` are the offline fallback when no
live schema is reachable and no per-profile cache exists. They are committed to
the repo and shipped inside the wheel.

## Layout

```
nsc/schemas/bundled/
├── manifest.yaml
├── netbox-4.6.0.json.gz
└── netbox-<other-version>.json.gz
```

`manifest.yaml`:

```yaml
schemas:
  - version: "4.6.0"
    file: "netbox-4.6.0.json.gz"
```

## Adding a new version

1. Spin up `netboxcommunity/netbox:<version>` locally (Docker compose snippet
   in `tests/e2e/docker-compose.yml`).
2. Wait for it to be healthy.
3. Fetch the schema:

   ```sh
   curl -sS http://localhost:8080/api/schema/?format=json | gzip -9 \
     > nsc/schemas/bundled/netbox-<version>.json.gz
   ```

4. Add an entry to `manifest.yaml`. Keep entries in chronological order (newest
   last) — `scripts/gen_docs.py` uses the last entry as the canonical source for
   the auto-generated CLI reference.
5. Run `just test` and `python scripts/gen_docs.py` to regenerate the
   reference pages with the new schema.
6. Commit both the new file and the updated `manifest.yaml` together.

## When to add a new version

- A new NetBox release lands (major or minor).
- Plugin authors report a schema-shape change `nsc` doesn't yet handle.
- The current bundled version is the only entry and it's getting stale (>6
  months).

Bundled schemas are large (~2MB compressed) — keep the list short. Drop old
versions when they're no longer cited by any active deployment.

## Why bundle schemas at all?

`nsc` always tries the live schema first. Bundling exists for two narrow cases:

1. **First-run offline.** A new install with no cache, no network — the user
   gets a usable command tree from the bundled schema.
2. **CI without a NetBox container.** `nsc commands --schema bundled-default
   --output json` produces a deterministic command-model for tests that
   don't need a live NetBox.
