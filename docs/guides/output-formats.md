# Output formats

`nsc` ships five output formats. Default is **table** on a TTY and **JSON** when
stdout is piped.

## The five formats

| Flag | Purpose |
|---|---|
| `--output table` (default for TTY) | Rich table with auto-selected columns |
| `--output json` (default when piped) | Records as a JSON array (single-record writes emit the resulting record dict) |
| `--output jsonl` | One JSON object per line — good for streaming |
| `--output yaml` | YAML; useful when you'll round-trip to `-f file.yaml` |
| `--output csv` | CSV with nested fields flattened to dotted paths (`status.label`) |

```sh
nsc dcim devices list                                   # table on TTY, JSON if piped
nsc dcim devices list -o json                           # explicit
nsc dcim devices list --output csv > devices.csv
nsc dcim devices list -o yaml > devices.yaml
nsc dcim devices list -o jsonl | jq '. | select(.status.value == "active")'
```

## Auto-selected columns

Heuristic for the table view:

1. Always `id`.
2. Then any field named `name`, `slug`, or `display`.
3. Then up to 6 scalar fields from the resource's GET response schema.

Override per `<tag> <resource>` in `~/.nsc/config.yaml`:

```yaml
columns:
  dcim:
    devices: [id, name, status, site, role]
```

Unknown column names are silently ignored, so the same config remains valid
across NetBox versions and plugin changes.

## Compact JSON

```sh
nsc dcim devices list -o json --compact > devices.json
```

One-line records — convenient for `jq` chains and ndjson tooling.

## Pagination and `--all`

```sh
nsc dcim devices list                       # default page (50 records)
nsc dcim devices list --all                 # follow `next` to completion
nsc dcim devices list --limit 200           # cap at 200
nsc dcim devices list --filter status=active --all
```

`--all` shows a Rich progress bar on TTY. For machine output, prefer
`--output json --all` and pipe.
