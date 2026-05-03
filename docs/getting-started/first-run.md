# First run

Two paths to your first command:

1. **Interactive wizard** — `nsc init` prompts for everything.
2. **Env vars** — `NSC_URL` + `NSC_TOKEN` and you're done; no config file needed.

## Interactive: `nsc init`

```sh
nsc init
```

The wizard prompts for:

- A **profile name** (e.g., `prod`, `lab`).
- The NetBox URL.
- A token (stored verbatim in `~/.nsc/config.yaml` by default; can be `!env NAME` indirection — see [Managing profiles](../guides/managing-profiles.md)).
- Whether to verify SSL.

It writes `~/.nsc/config.yaml`, fetches the schema once to warm the cache, and
exits. You can re-run with `nsc login --new --profile <name>` to add more later.

`nsc init` refuses to overwrite an existing config — use `nsc login --new`
to add more profiles non-interactively.

## Env-var only

For one-off use, agents, or CI:

```sh
export NSC_URL=https://netbox.example.com
export NSC_TOKEN=$(cat ~/.netbox-token)

nsc dcim devices list
```

No `~/.nsc/config.yaml` required. The cache lives at `~/.nsc/cache/adhoc/`
when there's no profile.

## Authenticate / verify a profile

```sh
nsc login                          # verify the default profile
nsc login --profile lab            # verify a specific profile
nsc login --new --profile staging --url https://netbox-staging.example.com
nsc login --rotate --profile prod  # rotate the token
```

`nsc login` calls `GET /api/users/tokens/?limit=1` and prints
`✓ authenticated as <user>, NetBox <version>` on success. On failure it emits
the standard `auth_error` envelope (exit 8).

## Your first read

```sh
nsc dcim devices list                       # default page (page_size=50)
nsc dcim devices list --all                 # paginate to completion
nsc dcim devices get 7                      # get by id
nsc ls devices                              # alias — matches devices.list
nsc dcim devices list --output json --all   # canonical machine-readable form
```

## Your first write

```sh
nsc dcim devices create --field name=test-1 --field site=2 --explain  # dry-run + reasoning
nsc dcim devices create --field name=test-1 --field site=2 --apply    # commit
nsc rm devices test-1 --apply                                          # delete via alias
```

Every write previews as a dry-run unless you pass `--apply`. See [Writes and safety](../guides/writes-and-safety.md) for the full discipline.
