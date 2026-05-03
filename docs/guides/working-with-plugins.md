# Working with plugins

NetBox plugins extend the OpenAPI schema. Because `nsc` builds its command tree
from that schema at startup, **every plugin endpoint becomes a command
automatically — no per-plugin code in `nsc`**.

## How plugin endpoints surface

If a plugin registers `tags: [my_plugin]` and a path `/api/plugins/my-plugin/widgets/`,
you get:

```sh
nsc my_plugin widgets list
nsc my_plugin widgets get 7
nsc my_plugin widgets create --field name=foo --apply
```

Verbs are derived from HTTP method + `operationId` exactly as for core endpoints.
Custom action endpoints (`POST /api/plugins/my-plugin/widgets/{id}/calibrate/`)
become e.g. `nsc my_plugin widgets calibrate 7 --apply`.

## Discovery

```sh
nsc commands --output json | jq '.tags | keys'        # every tag in your install
nsc describe my_plugin widgets                         # fields, filters, operations
nsc commands --output json | jq '.tags.my_plugin'      # full subtree
```

## Schema cache and plugin upgrades

The cache is keyed by the schema's SHA-256 hash. When you upgrade a plugin (or
any NetBox component that changes the schema), the next `nsc` invocation
notices the hash change and regenerates the command-model in the background. The
old `<schema_hash>.json` file becomes stale and gets cleaned by
`nsc cache prune` — see [Caching](../architecture/caching.md) for the details.

## When a plugin endpoint is missing

If `nsc` doesn't know about an endpoint you can hit with `curl`:

1. Check `nsc commands --output json | jq '.tags' | grep -i <name>` — the schema
   may use a different tag than you expect.
2. Run `nsc refresh --profile <name>` to force re-fetch the schema.
3. Confirm the endpoint is in `/api/schema/?format=json` for your install
   (some plugins generate routes lazily and don't register them with drf-spectacular).
