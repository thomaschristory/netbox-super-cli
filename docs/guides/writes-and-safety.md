# Writes and safety

`nsc` is **safe by default**: every write previews as a dry-run. Mutations
require an explicit `--apply` flag.

## The two-step rhythm

```sh
# 1. Preview — see exactly what would be sent.
nsc dcim devices create -f device.yaml

# 2. Commit.
nsc dcim devices create -f device.yaml --apply
```

Add `--explain` to the preview for the schema reasoning:

```sh
nsc dcim devices update 42 --field status=active --explain
# Annotates the resolved request with operationId, HTTP method, the matched path.
```

## Strict deletes

`--strict` makes a delete of an object that does not exist a hard failure:

```sh
nsc dcim devices delete 999 --apply --strict
# Missing object → not_found error, exit code 9 (instead of treating it as a no-op).
```

Without `--strict`, deleting an absent object is tolerated. Use `--strict` in
idempotency-sensitive automation where "already gone" should still surface.

## Bulk vs loop

When the input is a list (JSON array or NDJSON file or stdin) and the schema
exposes a bulk endpoint, `nsc` issues **one HTTP call**. When the schema lacks
the bulk variant, it loops record-by-record:

```sh
nsc dcim devices create -f devices.ndjson --apply              # one bulk call when supported
nsc dcim devices create -f devices.ndjson --no-bulk --apply    # forced loop
nsc dcim devices create -f devices.ndjson --on-error continue --apply   # don't stop on first failure
```

`--on-error continue` collects per-record failures, reports them in a summary
envelope, and exits with the worst error type's code.

## Input formats

| Extension | Format |
|---|---|
| `.yaml`, `.yml` | YAML |
| `.json` | strict JSON (object or array) |
| `.ndjson`, `.jsonl` | one JSON object per line |
| `-` (with `-f -`) | stdin; format auto-detected from the first 512 bytes |

Inline `--field key=value` pairs win over file content on overlap and can be
mixed with `-f`.

## Audit log

Every wire request and response is appended to `~/.nsc/logs/audit.jsonl` —
including dry-runs (with a flag indicating the request was not sent).

The audit file is **confidential**. Sensitive fields are redacted **before
write**, but the rest of the body is preserved verbatim. The live wire body
sent to NetBox is never modified.

### What gets redacted

A field is sensitive if its OpenAPI schema has `format: password` OR its name
(case-insensitive) is in the canonical set:

```
password, secret, token, api_key, apikey, private_key, passphrase, client_secret
```

Both top-level and nested fields are redacted; arrays of objects are redacted
per-element. Failed writes do NOT unredact — the audit record stays
sanitized regardless of what happened on the wire.

### What is NOT redacted

- The endpoint URL (no query parameters from the body).
- Response bodies (NetBox's response is recorded as-is — if it echoes back a
  password, that's NetBox's bug to fix).
- Headers other than `Authorization` (which never enters the audit file).

## Error envelope and exit codes

On failure with `--output json`:

```json
{
  "error": "NetBox API 400 on https://...",
  "type": "validation",
  "endpoint": "https://...",
  "status_code": 400,
  "operation_id": "dcim_devices_create",
  "details": { "source": "server", "body_excerpt": "..." }
}
```

A malformed line in an NDJSON/JSONL bulk input is reported as an `input_error`
envelope and exits **4** (the same code as a request `validation` error). Any
other bad input — a malformed single JSON/YAML document, an empty list, a
missing `-f` file — is a `client` error and exits **6**. A `--strict`
delete of a missing object exits **9** (`not_found`).

The full exit-code table lives at [Exit codes](../reference/exit-codes.md).
Type values and exit codes are locked — they never change once shipped.
