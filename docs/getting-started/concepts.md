# Concepts

A short tour of the model `nsc` uses for everything.

## Profiles

A **profile** is a named NetBox instance: URL + token + a few options. They live
in `~/.nsc/config.yaml`:

```yaml
default_profile: prod
profiles:
  prod:
    name: prod
    url: https://netbox.example.com
    token: !env NSC_PROD_TOKEN
    verify_ssl: true
  lab:
    name: lab
    url: https://netbox-lab.local
    token: !env NSC_LAB_TOKEN
    verify_ssl: false
```

Pick one with `--profile <name>`, override at the command line with `--url` /
`--token`, or skip the file entirely with `NSC_URL` + `NSC_TOKEN` env vars
("adhoc" mode). See [Managing profiles](../guides/managing-profiles.md).

## Dynamic command tree

The command tree is built **at startup** from the live NetBox OpenAPI schema:

```
nsc <tag> <resource> <verb> [args] [options]
   │     │           │
   │     │           └── derived from HTTP method + operationId:
   │     │               GET /things/      → list
   │     │               GET /things/{id}/ → get
   │     │               POST /things/     → create
   │     │               PATCH /things/{id}/ → update
   │     │               PUT /things/{id}/ → replace
   │     │               DELETE /things/{id}/ → delete
   │     └── path segment (e.g., devices, prefixes)
   └── OpenAPI tag (e.g., dcim, ipam)
```

This means **every endpoint your install exposes is a command — including plugin
endpoints — without per-plugin code in `nsc`**.

A short curated alias layer sits on top: `nsc ls`, `nsc get`, `nsc rm`, `nsc search`.

## Dry-run / apply

Writes default to dry-run. The CLI shows the resolved request and exits 0
WITHOUT sending it.

```sh
nsc dcim devices create --field name=foo --field site=1
# → JSON of what would be sent
nsc dcim devices create --field name=foo --field site=1 --apply
# → actually sends
```

Add `--explain` to a dry-run to see the schema reasoning ("PATCH because of
operationId `dcim_devices_partial_update`").

## Audit log

Every wire request and its response are appended to
`~/.nsc/logs/audit.jsonl`. Sensitive fields (`password`, `token`, …) are
redacted before write — the live wire body is never modified. See
[Writes and safety](../guides/writes-and-safety.md) for the full contract.

## Error envelope

When something goes wrong with `--output json`, `nsc` emits a single-line JSON envelope:

```json
{
  "error": "human message",
  "type": "validation",
  "endpoint": "https://...",
  "method": "POST",
  "status_code": 400,
  "operation_id": "dcim_devices_create",
  "details": { ... }
}
```

Each `type` maps to a stable exit code (see [Exit codes](../reference/exit-codes.md)).
The contract is locked — `type` values and exit codes do not change once
shipped.
