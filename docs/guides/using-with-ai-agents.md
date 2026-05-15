# Using with AI agents

`nsc` was designed alongside agentic coding tools (Claude Code, Codex, Gemini
CLI, GitHub Copilot CLI) and ships a portable Skill bundle so they can drive it
correctly without trial-and-error.

## What an agent needs to know

| Feature | Mechanism |
|---|---|
| Predictable command shape | `nsc <tag> <resource> <verb>` — derived from the OpenAPI schema, no hand-curation |
| Self-describing | `nsc commands --schema <path-or-url> --output json` dumps the full command-model (tags → resources → operations) |
| Stable machine output | `--output json` everywhere; data on stdout, errors as JSON on stderr (or stdout when `--output json`), non-zero exit on failure |
| Stable error envelope | `{error, type, endpoint, method, status_code, operation_id, details}` — locked schema, see [Exit codes](../reference/exit-codes.md) |
| Safe by default | Writes preview as dry-runs; `--apply` is the only path to mutation |
| Auditable | `~/.nsc/logs/audit.jsonl` records every wire request and response (passwords redacted) |

## Bundled portable Skill

`nsc` ships a portable Skill bundle at `skills/netbox-super-cli/SKILL.md`
(installed inside the wheel). Install it into a known agent harness with:

```sh
nsc skill install --target claude-code            # dry-run; prints the destination
nsc skill install --target claude-code --apply    # actually copies
```

Or export the bundled `SKILL.md` to an arbitrary directory:

```sh
nsc skill export ./my-skills                      # dry-run; prints the would-write path
nsc skill export ./my-skills --apply              # actually copies
```

`nsc skill export <dir>` always writes to `<dir>/netbox-super-cli/SKILL.md` —
the `netbox-super-cli/` subdirectory is inserted for you. Both `skill install`
and `skill export` are **dry-run unless `--apply`** is passed.

Use `--output json` for programmatic consumers; the dry-run envelope contains
the resolved destination path.

### Per-target resolved paths

| Target       | Convention | Resolved path                                                  |
|--------------|------------|----------------------------------------------------------------|
| claude-code  | confirmed  | `~/.claude/skills/netbox-super-cli/SKILL.md`                   |
| codex        | confirmed  | `~/.agents/skills/netbox-super-cli/SKILL.md`                   |
| gemini       | manual     | (no programmatic install; prints manual instructions)          |
| copilot      | manual     | (no programmatic install; prints manual instructions)          |

For targets marked `manual`, `nsc skill install --target <t>` prints
actionable instructions (exit 0) instead of writing a guessed path.
The bundled Skill content is at `skills/netbox-super-cli/SKILL.md` in
this repo and inside the installed wheel; for `manual` targets, paste
its content into your tool's project-scoped configuration (e.g.
`GEMINI.md` for Gemini CLI, `.github/copilot-instructions.md` for
GitHub Copilot CLI).

## Agent prompts that work well

When briefing an agent to use `nsc`, include:

1. **The dry-run / apply discipline.** "All writes preview by default. Use
   `--apply` to commit." Otherwise the agent will paste `--apply` into every
   read command.
2. **The output format.** "Use `--output json` for everything. Errors are JSON
   envelopes — read `.type` for the category, the exit code for control flow."
3. **Discovery commands.** "Run `nsc commands --schema <path-or-url> --output
   json` to see the whole surface (tags → resources → operations)." This
   prevents the agent from guessing endpoints.
4. **The audit log.** "If a command fails unexpectedly, check
   `~/.nsc/logs/audit.jsonl` — it has the exact request and response." This
   replaces guesswork with evidence.

## Patterns that don't work

- **Asking the agent to skip dry-run.** Just don't. The dry-run is the agent's
  one chance to surface an objection.
- **Hand-curated endpoint lists in the prompt.** They go stale on every NetBox
  upgrade. Use `nsc commands --schema <path-or-url> --output json` instead.
- **Authenticating per-command.** Configure a profile (or env vars) once at
  session start.
