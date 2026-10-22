# NetBox Branching

If your NetBox runs the [NetBox Branching plugin](https://netboxlabs.com/docs/extensions/branching/)
(`netboxlabs-netbox-branching`), `nsc` can make your changes in a **branch**
instead of on main. You stage writes in the branch, review the diff, and then
merge them into main. This works the same way for people and for AI agents.

Requires NetBox 4.7 and plugin 1.2.x (tested against NetBox 4.7.3 and plugin 1.2.2).

```sh
nsc branch create add-london --use     # create, wait until ready, make it sticky
nsc dcim sites create -f london.yaml --apply   # lands in the branch, not main
nsc branch diff                        # review what the branch changes
nsc branch merge                       # dry-run: validates the merge server-side
nsc branch merge --apply               # merge into main
nsc branch use --main                  # back to main
```

## Choosing the branch

Every command, including dynamic resource commands, aliases and the TUI, runs
in the active branch. `nsc` sends the plugin's `X-NetBox-Branch` header with
the branch's `schema_id`. You refer to a branch by name, or by schema_id if
you prefer.

The active branch comes from the first of these that is set:

| Source | Example | Lifetime |
|---|---|---|
| `--branch NAME` | `nsc --branch add-london ls sites` | one command |
| `NSC_BRANCH` | `export NSC_BRANCH=add-london` | the shell / CI job |
| profile `branch:` | written by `nsc branch use NAME` | sticky, until `nsc branch use --main` |

`--branch main` or `NSC_BRANCH=main` forces main for that invocation even when
the profile has a sticky branch.

`--branch` is a global option and must come **before** the subcommand
(`nsc --branch X dcim sites list`). After the subcommand, `--branch` belongs to
that command, for example the Branching plugin's own `changes list` filter, and
doesn't switch branches.

`nsc branch use` needs a saved profile to store the branch on. With only
`NSC_URL`/`NSC_TOKEN` set (no profile), use `NSC_BRANCH` or `--branch`.

## Knowing where you are

When a branch is active, every command prints one line to **stderr**:

```
⎇ branch: add-london
```

stdout is untouched, so `-o json` output piped elsewhere stays clean. The TUI
shows the branch in its header in the warning colour. `nsc branch current`
prints the active branch and where it came from (`flag`, `env` or `profile`),
or `main`.

Every request made in a branch is recorded in the [audit log](audit-log.md)
with its `X-Netbox-Branch` header (the branch's schema_id). When a command
fails while a branch is active, its error envelope names the branch in
`details.branch`, whatever the failure is.

A branch that is literally named `main` can still be selected by its
schema_id. `nsc branch use` stores the schema_id for such a branch, because the
name would read back as "force main".

## When the branch can't be used

If the active branch doesn't exist, or exists but isn't `ready` (it's
merged, archived, still provisioning, or failed), the command **fails without
sending anything** and never falls back to main:

| Situation | Error type | Exit |
|---|---|---|
| Branching plugin not installed | `config` | 12 |
| Branch not found | `not_found` | 9 |
| Branch not `ready` (e.g. merged) | `config` | 12 |
| Name matches one branch and schema_id of another | `input_error` | 4 |

The message says how to get back to main: `nsc branch use --main`, or
`--branch main` for a single command. `nsc branch …` commands never run inside
a branch, so `nsc branch use --main` always works.

## Commands

| Command | What it does |
|---|---|
| `nsc branch list` | All branches; the active one has `active: true`. |
| `nsc branch show [NAME]` | One branch (default: the active one). |
| `nsc branch current` | Active branch and its source, or `main`. No network call. |
| `nsc branch create NAME [--description] [--use] [--no-wait]` | Create the branch and wait until it's `ready`. `--use` then makes it sticky. |
| `nsc branch use NAME` / `--main` | Set / clear the profile's sticky branch. Checks that the branch is `ready` first. |
| `nsc branch diff [NAME]` | Staged changes: action, object type, object, changed fields. `-o json` gives the full plugin records. |
| `nsc branch sync [NAME]` | Pull main's changes into the branch. |
| `nsc branch merge [NAME]` | Merge the branch into main. |
| `nsc branch revert [NAME]` | Undo a merged branch on main. |
| `nsc branch archive [NAME]` | Archive a merged branch (drops its schema). |
| `nsc branch delete NAME` | Delete a branch. |

### Dry-run by default

Like every other `nsc` write, `sync`, `merge`, `revert`, `archive` and
`delete` change nothing unless you pass `--apply`:

- `sync`, `merge` and `revert` without `--apply` still run the plugin's job
  with `commit: false`, so the server checks that the operation would succeed
  and then rolls it back.
- `archive` and `delete` without `--apply` only print what they would do.

`sync`, `merge` and `revert` wait for the background job to finish (up to
`--timeout`, 600 s by default) and print the job's log lines on stderr. Pass
`--no-wait` to return as soon as the job is queued.

A job that ends in `errored` exits **4** (`validation`), with the job's error
in `details.job_error`. This happens, for example, when a Change Request
policy blocks the merge.

### Conflicts

If main and the branch changed the same fields of an object, `sync` and
`merge` fail with exit **10** (`conflict`), and `details.conflicts` lists each
object together with its original, branch and main values. After reviewing
them, re-run with `--acknowledge-conflicts` to proceed; the branch's values
win.

## For agents

Agents should set `NSC_BRANCH` rather than `nsc branch use`. It works without
a saved profile, and it doesn't change the user's config:

```sh
nsc branch create agent-change-123 -o json
export NSC_BRANCH=agent-change-123
nsc dcim devices create -f devices.ndjson --apply -o json
nsc branch diff agent-change-123 -o json   # hand this to a human for review
```

The commands are the same for people and agents. Whether an agent may run
`nsc branch merge --apply` is up to the session's own rules; `nsc` doesn't
enforce it.
