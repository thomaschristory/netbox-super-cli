# First run

Two paths to your first command:

1. **Interactive wizard** — `nsc init` prompts for everything.
2. **Env vars** — `NSC_URL` + `NSC_TOKEN` and you're done; no config file needed.

## Interactive: `nsc init`

```sh
nsc init
```

The wizard prompts, in order, for:

- A **profile name** (default `default`; e.g., `prod`, `lab`).
- The NetBox URL.
- **Verify SSL certificates?** (default yes).
- **Token storage** — `plaintext` or `env` (default `plaintext`).
- Then either an **environment variable name** (if you chose `env` storage — written as
  an `!env NAME` indirection) or the **token** itself (hidden input, stored verbatim in
  `~/.nsc/config.yaml`). See [Managing profiles](../guides/managing-profiles.md).

`nsc init` is offline-safe: it does not contact NetBox. On success it writes
`~/.nsc/config.yaml` with the profile, prints the path, and suggests
`nsc login --profile <name>` as the next step. It does **not** fetch the
schema — run `nsc login` afterwards to verify the token and prime the schema
cache (see below).

`nsc init` refuses to overwrite an existing config — use
`nsc login --new --profile <name> --url <url>` to add more profiles.

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
nsc login --fetch-schema           # verify, then fetch & cache the live schema
```

`nsc login` probes `GET /api/status/` and `GET /api/users/tokens/?limit=1`
(both must succeed) and prints `✓ authenticated as <user>, NetBox <version>`
on success. On failure it emits the standard auth error envelope
(`type: auth`, exit 8).

`--new` requires both `--profile` and `--url`, prompts for the token
(hidden input), verifies it before writing, and persists the profile. After a
successful `--new` it also asks **"Fetch and cache the live schema now?"**
(default **yes**) — accepting primes the schema cache so your first real
command skips the bootstrap fetch. Pass `--fetch-schema` to any `nsc login`
(or `--new`) to fetch the schema unconditionally without the prompt;
`--rotate` neither prompts for nor fetches the schema.

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
