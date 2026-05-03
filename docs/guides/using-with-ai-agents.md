# Using with AI agents

`nsc` was designed alongside agentic coding tools (Claude Code, Codex, Gemini
CLI, GitHub Copilot CLI) and ships a portable Skill bundle so they can drive it
correctly without trial-and-error.

## What an agent needs to know

| Feature | Mechanism |
|---|---|
| Predictable command shape | `nsc <tag> <resource> <verb>` — derived from the OpenAPI schema, no hand-curation |
| Self-describing | `nsc commands --output json` dumps the full command-model; `nsc describe <tag> <resource>` dumps a resource's fields/filters/operations |
| Stable machine output | `--output json` everywhere; data on stdout, errors as JSON on stderr (or stdout when `--output json`), non-zero exit on failure |
| Stable error envelope | `{error, type, endpoint, method, status_code, operation_id, details}` — locked schema, see [Exit codes](../reference/exit-codes.md) |
| Safe by default | Writes preview as dry-runs; `--apply` is the only path to mutation |
| Auditable | `~/.nsc/logs/audit.jsonl` records every wire request and response (passwords redacted) |

## Bundled portable Skill

> **Phase 5b note:** the `nsc skill install` helper and the bundled
> `skills/netbox-super-cli/SKILL.md` content land in **Phase 5c** (the next
> sub-phase after this one). For now, point your agent at the [CLI
> reference](../reference/cli.md) and this guide.

After 5c, install the Skill into your tool with one command:

```sh
nsc skill install --target claude-code --apply
nsc skill install --target codex --apply
nsc skill install --target gemini --apply
nsc skill install --target copilot --apply
```

## Agent prompts that work well

When briefing an agent to use `nsc`, include:

1. **The dry-run / apply discipline.** "All writes preview by default. Use
   `--apply` to commit." Otherwise the agent will paste `--apply` into every
   read command.
2. **The output format.** "Use `--output json` for everything. Errors are JSON
   envelopes — read `.type` for the category, the exit code for control flow."
3. **Discovery commands.** "Run `nsc commands --output json` to see the whole
   surface. Run `nsc describe <tag> <resource>` for a specific resource's
   fields." This prevents the agent from guessing endpoints.
4. **The audit log.** "If a command fails unexpectedly, check
   `~/.nsc/logs/audit.jsonl` — it has the exact request and response." This
   replaces guesswork with evidence.

## Patterns that don't work

- **Asking the agent to skip dry-run.** Just don't. The dry-run is the agent's
  one chance to surface an objection.
- **Hand-curated endpoint lists in the prompt.** They go stale on every NetBox
  upgrade. Use `nsc commands --output json` instead.
- **Authenticating per-command.** Configure a profile (or env vars) once at
  session start.
