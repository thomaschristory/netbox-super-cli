---
name: netbox-super-cli
description: Use when the user asks to query, create, update, or delete NetBox infrastructure data (devices, sites, racks, IPs, prefixes, VLANs, tenants, etc.) via `nsc`. Drives the dynamic NetBox CLI generated from the live OpenAPI schema.
when_to_use: The user has `nsc` installed (`pip install netbox-super-cli` or `uv tool install netbox-super-cli`) and asks anything that maps to a NetBox resource — listing, creating, updating, deleting, bulk operations, or audit-log inspection. Also use when the user is debugging a NetBox automation that calls `nsc`.
---

# netbox-super-cli (`nsc`)

`nsc` is a dynamic NetBox CLI: every subcommand is generated from the live
OpenAPI schema of the NetBox instance you point it at. There is no hand-curated
endpoint list to go stale.

## What's installed

- `nsc` is on PATH after `pip install netbox-super-cli`.
- Config lives at `~/.nsc/config.yaml`.
- Audit log lives at `~/.nsc/logs/audit.jsonl` (one JSON-line per request/response;
  passwords are redacted).
- Cache lives at `~/.nsc/cache/<profile>/<schema-hash>.json`.

## Command shape

```
nsc <tag> <resource> <verb> [args] [--apply] [--output json]
```

- `<tag>` — the OpenAPI tag, e.g., `dcim`, `ipam`, `tenancy`, `circuits`, `extras`.
- `<resource>` — plural form, e.g., `devices`, `prefixes`, `tenants`, `vlans`.
- `<verb>` — `list`, `get`, `create`, `update`, `delete`. (Bulk variants exist
  for write verbs via `-f <file>` — use a `.ndjson` / `.jsonl` extension to trigger
  NDJSON mode.)

A few curated aliases skip the tag:

- `nsc ls <resource>` — alias for `nsc <tag> <resource> list`.
- `nsc init` — interactive config bootstrap.
- `nsc login` — interactive token capture.
- `nsc commands` — dump the entire generated command tree (useful for discovery).
- `nsc describe <tag> <resource>` — dump one resource's fields, filters, operations.

## Dry-run / apply discipline

ALL writes are dry-runs by default. The `--apply` flag is the only path to
mutation:

```
nsc dcim devices create -f device.yaml          # dry-run; prints what would happen
nsc dcim devices create -f device.yaml --apply  # actually creates
```

Bulk writes use `-f <file>` with a `.ndjson` / `.jsonl` extension (one JSON
object per line) and the same `--apply` rule applies. Read commands (`list`,
`get`, `describe`) ignore `--apply` — never paste it into a read by reflex.

## Stable JSON output

Use `--output json` for everything an agent reads:

```
nsc ls devices --output json | jq '.[] | select(.status.value == "active")'
```

Errors come back as JSON envelopes (on stderr by default; on stdout when
`--output json` is set). The envelope shape is locked:

```json
{
  "error": "human-readable message",
  "type": "auth | not_found | validation | conflict | rate_limited | server | transport | schema | config | client | internal | input_error | ambiguous_alias | unknown_alias",
  "endpoint": "/api/dcim/devices/",
  "method": "POST",
  "status_code": 400,
  "operation_id": "dcim_devices_create",
  "details": { …field-keyed errors when applicable… }
}
```

Exit codes correspond to envelope `type` — see `nsc commands --output json` or
the project's `reference/exit-codes.md` page.

## Common patterns

- **Discover the surface:** `nsc commands --output json | jq 'keys'`
- **Discover a resource:** `nsc describe dcim devices --output json`
- **List with filters:** `nsc dcim devices list --site mysite --status active --output json`
- **Get one:** `nsc dcim devices get 42 --output json`
- **Create from a YAML file:** `nsc dcim devices create -f new-device.yaml --apply`
- **Bulk create from NDJSON:** `nsc dcim devices create -f devices.ndjson --apply`
- **Update a field:** `nsc dcim devices update 42 --status decommissioning --apply`
- **Delete:** `nsc dcim devices delete 42 --apply` (preview first WITHOUT `--apply`)

## Performance: prefer one bulk call to many small ones

Each `nsc` invocation costs at least one HTTP round-trip to NetBox. When
operating on many objects, **prefer one filtered list call to N individual
gets, and one NDJSON write to a shell loop of single writes.** A loop of
1,000 patches is 1,000+ round-trips; a single NDJSON apply is one bulk
operation.

### Read patterns

- **Need every interface on a device?** Use `list` with a server-side
  filter, not a loop:
  ```bash
  # GOOD — one call, returns all matching rows
  nsc dcim interfaces list --device 42 --all --output json

  # BAD — N+1 round-trips
  nsc dcim devices get 42 --output json | jq '.interfaces[]' | \
    while read id; do nsc dcim interfaces get "$id"; done
  ```
- **Need a subset by some non-filterable property?** Pull the wider set
  once, then `jq` locally:
  ```bash
  nsc dcim interfaces list --device 42 --all --output json \
    | jq '[.[] | select(.enabled == true and (.name | startswith("Gi")))]'
  ```
- **Working across many devices? Scope once, filter locally.** Don't
  loop `nsc dcim interfaces list --device <id>` over every device — pull
  the broadest reasonable scope (a site, a role, a device type) in a
  single call, then narrow with `jq`. Server-side filters compose, so
  pick the tightest scope NetBox can apply for you:
  ```bash
  # GOOD — one call scoped to a site, local filtering by device list
  nsc dcim interfaces list --site dc1 --all --output json \
    | jq --argjson ids '[42, 43, 44]' \
        '[.[] | select(.device.id as $d | $ids | index($d))]'

  # GOOD — one call scoped to a role, then group by device
  nsc dcim interfaces list --device_role leaf-switch --all --output json \
    | jq 'group_by(.device.name)'

  # BAD — N round-trips, one per device
  for id in 42 43 44; do
    nsc dcim interfaces list --device "$id" --all --output json
  done
  ```
  The same pattern applies to IPs, cables, inventory items, and any
  child resource: filter by the parent scope (site, tenant, role,
  device-type), fetch once, partition locally.
- **Pagination defaults:** `list` returns the first page (50 rows by
  default). Pass `--all` to follow `next` links until exhausted, or
  `--limit N` for a hard cap. `nsc describe <tag> <resource>` reveals
  which fields can be filtered server-side.
- **Don't query `nsc commands` or `nsc describe` per-resource in a
  loop.** They serialize the whole command tree; cache the output once
  per session.

### Write patterns

- **Bulk writes go through `-f <file>.ndjson --apply`.** One JSON object
  per line; `nsc` streams them through a single bulk endpoint where the
  schema supports it, otherwise issues one request per line *with shared
  auth and connection pooling* — still much faster than a shell loop:
  ```bash
  # GOOD — one nsc invocation, connection reuse
  nsc dcim interfaces update -f changes.ndjson --apply

  # BAD — N invocations, N TLS handshakes, N schema-cache lookups
  while read line; do
    id=$(echo "$line" | jq .id)
    nsc dcim interfaces update "$id" -f <(echo "$line") --apply
  done < changes.ndjson
  ```
- **Generate the NDJSON once** with whatever scripting tool you prefer
  (`jq`, Python, awk). Don't re-run `list` between every patch.

### Schema fetches

`nsc` fetches `/api/schema/` to build its command tree, then caches the
result under `~/.nsc/cache/<profile>/<schema-hash>.json`. By default the
cache is trusted for 24h (`schema_refresh: daily` in
`~/.nsc/config.yaml`), so back-to-back commands don't repeat the schema
GET. Force a refresh with `--refresh-schema` (one-shot) or set
`defaults.schema_refresh: on-hash-change` if you need every invocation
to verify against the live schema. Other policies: `manual` (cache
indefinitely until manually refreshed), `weekly` (7-day TTL).

## When something fails

1. Check the exit code (`echo $?`) — the type is in `EXIT_CODES`.
2. Check the audit log: `tail -n 20 ~/.nsc/logs/audit.jsonl | jq`.
   The exact request and response are recorded.
3. Re-run with `--debug` for verbose logging on stderr.

## What NOT to do

- DO NOT skip `--apply`'s dry-run by reflex. The dry-run is your one chance to
  surface an objection BEFORE the wire request.
- DO NOT hand-curate endpoint lists in your reasoning. Use
  `nsc commands --output json` instead — endpoints change with NetBox versions.
- DO NOT authenticate per-command. Configure a profile (`nsc init` then
  `nsc login`) once at session start; `--profile <name>` switches between them.
- DO NOT assume singular resource names. Plural-only is the v1 stance:
  `nsc ls devices`, not `nsc ls device`.

## Profile management

- `nsc init` — first-time setup; writes `~/.nsc/config.yaml`.
- `nsc login` — interactive token capture for the active profile.
- `nsc profiles list` — show configured profiles.
- `nsc --profile prod ls devices` — one-shot profile override.

## Cache management

The on-disk cache speeds up repeated invocations against the same NetBox
schema. By default the cache is trusted for 24h before re-fetching the
live schema (see [Schema fetches](#schema-fetches) above).

- `nsc cache prune` — show what would be deleted (orphan profile dirs
  and stale-hash files).
- `nsc cache prune --apply` — actually delete.
- `nsc --refresh-schema <subcmd>` — force a one-shot live re-fetch
  bypassing the TTL.

## NetBox Device Type Library

The [NetBox Device Type Library](https://github.com/netbox-community/devicetype-library)
is a community-maintained collection of device type YAML definitions for hundreds of
real-world hardware devices (routers, switches, servers, PDUs, firewalls, etc.). It is
the canonical source for importing device types you don't want to define by hand, and is
especially useful for demo setups.

### Library YAML vs. NetBox API format

The library stores definitions in its own YAML dialect. The NetBox API (and therefore
`nsc`) uses a slightly different shape. The key differences:

| Library field | NetBox API field | Notes |
|---|---|---|
| `manufacturer: Cisco` | `manufacturer: {name: "Cisco", slug: "cisco"}` | both `name` and `slug` are required |
| `interfaces:` | separate `POST /api/dcim/interface-templates/` | component templates are separate resources |
| `console-ports:` | separate `POST /api/dcim/console-port-templates/` | same pattern |
| `power-ports:` | separate `POST /api/dcim/power-port-templates/` | same pattern |
| `module-bays:` | separate `POST /api/dcim/module-bay-templates/` | same pattern |

### Import workflow

```bash
# 1. Clone the library (once)
git clone https://github.com/netbox-community/devicetype-library.git

# 2. Find the device type you want
ls devicetype-library/device-types/Cisco/

# 3. Ensure the manufacturer exists in NetBox (create if missing)
nsc dcim manufacturers list --slug cisco --output json   # check first
nsc dcim manufacturers create --field name=Cisco --field slug=cisco --apply

# 4. Create the device type (body only — no component templates yet)
nsc dcim device-types create -f device-type-body.yaml --apply

# 5. Get the newly created device type's ID
DT_ID=$(nsc dcim device-types list --slug <slug> --output json | jq '.[0].id')

# 6. Add component templates (repeat for each component type present in the library YAML)
nsc dcim interface-templates create -f iface-templates.ndjson --apply
nsc dcim console-port-templates create -f console-templates.ndjson --apply
nsc dcim power-port-templates create -f power-templates.ndjson --apply
```

### Device type body YAML (for `nsc dcim device-types create -f`)

Translate the library YAML into the API shape before passing to `nsc`:

```yaml
# device-type-body.yaml
manufacturer:
  name: Cisco
  slug: cisco
model: "Catalyst 2960-24TC-L"
slug: cisco-catalyst-2960-24tc-l
u_height: 1
is_full_depth: true
```

### Component template NDJSON (one object per line)

Each component template must reference the parent device type's `device_type` ID:

```jsonl
{"device_type": 42, "name": "GigabitEthernet0/1", "type": "1000base-t"}
{"device_type": 42, "name": "GigabitEthernet0/2", "type": "1000base-t"}
```

Generate this from the library YAML with any scripting tool (jq, Python, etc.) before
passing to `nsc` via `-f <file>.ndjson`.

### Demo / seed workflow

To quickly seed a fresh NetBox with common hardware for demos:

```bash
# List all manufacturer directories in the library
ls devicetype-library/device-types/
```

For each YAML file, apply steps 3–6 above. Because `nsc` dry-runs by default, you can
preview each step before committing.

### What NOT to do

- DO NOT pass the raw library YAML directly to `nsc` — it will fail schema validation
  because `manufacturer` is a string in the library but a nested object in the API.
- DO NOT try to create component templates before the parent device type exists; they
  all require a `device_type` foreign key.
- DO NOT import duplicates blindly; check `nsc dcim device-types list --slug <slug>`
  first and skip if it already exists.

## See also

- `nsc commands --output json` — the full command tree.
- Project docs site (deployed on every release tag).
- [NetBox Device Type Library](https://github.com/netbox-community/devicetype-library) — community YAML definitions.
