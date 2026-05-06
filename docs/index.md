# netbox-super-cli

Dynamic NetBox CLI driven by the live OpenAPI schema. The same `nsc` binary works
against any NetBox version (4.4+) and exposes plugin-provided endpoints automatically
because the schema — not hand-written code — defines the surface.

## Why nsc

- **Plugins just work.** New endpoints from any installed plugin appear as commands automatically.
- **Multi-instance.** Named profiles per NetBox instance, plus env-var overrides.
- **Safe by default.** Writes preview as dry-runs unless you pass `--apply`.
- **Agent-friendly.** Deterministic command shape, machine-readable JSON output, stable error envelope with documented exit codes.

## Three killer examples

```sh
# 1. Read every device with status=active across the whole instance.
nsc dcim devices list --status active --all --output json

# 2. Bulk-create devices from an NDJSON file (preview first, then apply).
nsc dcim devices create -f devices.ndjson --explain
nsc dcim devices create -f devices.ndjson --apply

# 3. Run safely from CI: machine-readable output, locked exit codes.
NSC_URL=https://netbox.example.com NSC_TOKEN=$NSC_TOKEN \
  nsc ipam prefixes create --field prefix=10.0.0.0/24 --apply --output json
```

## Where to next

- **First time?** Start with [Install](getting-started/install.md) → [First run](getting-started/first-run.md) → [Concepts](getting-started/concepts.md).
- **Looking for a specific pattern?** Jump to the [Guides](guides/managing-profiles.md).
- **Need an exact command?** [CLI reference](reference/cli.md) is auto-generated from the bundled NetBox schema.
- **Curious how it works?** Read [Architecture: overview](architecture/overview.md).
