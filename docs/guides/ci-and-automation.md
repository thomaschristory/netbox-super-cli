# CI and automation

`nsc` is designed to be agent- and CI-friendly: deterministic command shape,
machine-readable output, locked exit codes, no interactive prompts unless you
ask for them.

## The minimum viable CI invocation

```sh
export NSC_URL=https://netbox.example.com
export NSC_TOKEN=$NETBOX_TOKEN  # from your secrets manager

nsc dcim devices create -f new-devices.ndjson --apply --output json --on-error continue
```

This:

- Skips `~/.nsc/config.yaml` entirely (env vars provide URL + token).
- Uses NDJSON for line-by-line input (works well with generated payloads).
- Continues on per-record failure and reports a summary envelope.
- Emits machine-readable output to stdout.
- Returns a stable exit code.

## Exit-code-driven control flow

```sh
if nsc dcim devices get foo --output json > /tmp/foo.json; then
  echo "found"
else
  case $? in
    9)  echo "not found";;
    8)  echo "auth failure";;
    *)  echo "other failure"; cat /tmp/foo.json;;
  esac
fi
```

The full table is at [Exit codes](../reference/exit-codes.md).

## Combining with `jq`

```sh
# Find every device that hasn't been seen in 7 days.
nsc dcim devices list --all --output json \
  | jq '[.[] | select(.last_seen < (now - 7*86400 | strftime("%Y-%m-%dT%H:%M:%S")))]'

# Stream-process with jsonl.
nsc dcim devices list --all --output jsonl \
  | jq -c 'select(.status.value == "active")' \
  > /tmp/active.jsonl
```

## GitHub Actions example

```yaml
name: sync-from-source-of-truth
on:
  schedule: [{ cron: "0 6 * * *" }]
  workflow_dispatch:

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install netbox-super-cli
      - run: nsc dcim devices create -f devices.ndjson --apply --on-error continue --output json
        env:
          NSC_URL: ${{ vars.NETBOX_URL }}
          NSC_TOKEN: ${{ secrets.NETBOX_TOKEN }}
```

## Caching the command-model in CI

`nsc` caches the generated command-model at `~/.nsc/cache/<profile>/<hash>.json`.
In CI, cache `~/.nsc/cache/` between runs to skip the schema fetch + parse:

```yaml
- uses: actions/cache@v4
  with:
    path: ~/.nsc/cache/
    key: nsc-cache-${{ hashFiles('netbox-version.txt') }}
```

The cache invalidates automatically on any schema-hash change, so a stale cache
just means one extra fetch on the next run — never a wrong command tree.

## Pre-flight check in scripts

```sh
# Verify connectivity + auth before doing anything mutating.
nsc login || { echo "auth failed"; exit 1; }
```

`nsc login` verifies the active profile's token (exit **8** on auth failure,
**12** on a config/profile problem). It takes no `--output` flag; on failure it
prints the standard JSON error envelope.

## Cleaning up the cache

`nsc cache prune` removes orphan profile dirs and stale-hash files (it is
dry-run unless you pass `--apply`). Add `--max-age N` to also prune cache
files older than N days. Safe to run unattended; never deletes the `adhoc`
cache.
