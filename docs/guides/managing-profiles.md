# Managing profiles

Profiles live in `~/.nsc/config.yaml`. `nsc profiles ...` covers the lifecycle.

## List

```sh
nsc profiles list
nsc profiles list --output json
```

## Add a profile non-interactively

```sh
nsc profiles add lab --url https://netbox-lab.local --token "$LAB_TOKEN"
```

This is the scriptable equivalent of `nsc login --new --profile lab`. It runs
the same verification (`GET /api/status/` plus `GET /api/users/tokens/?limit=1`)
before persisting. Refuses if `lab` already exists.

## Add a profile interactively

```sh
nsc init                                                              # first time, no config yet
nsc login --new --profile staging --url https://netbox-staging.local  # subsequent profiles
```

`nsc login --new` requires both `--profile` and `--url`, then prompts for the
token (hidden input) and runs verification before persisting. Add `--store env
--env-var NAME` to store the token as an `!env NAME` reference instead of
plaintext. Refuses (exit 12) if the profile already exists.

After a successful `--new`, `nsc` interactively asks **"Fetch and cache the
live schema now?"** (default **yes**) — accept it to pre-warm the command-model
cache, or pass `--fetch-schema` to fetch unconditionally without the prompt.

## Verify, rotate, and fetch the schema

```sh
nsc login                                    # verify the default profile's token
nsc login --profile lab                      # verify a specific profile
nsc login --profile lab --fetch-schema       # verify, then refresh the cached schema
nsc login --rotate --profile lab             # prompt for a new token, verify, then persist
```

`nsc login` (bare or with `--profile`) verifies the token by probing
`GET /api/status/` and `GET /api/users/tokens/?limit=1`; it writes no config.
`--fetch-schema` additionally force-refreshes the cached OpenAPI schema.
`--rotate` requires `--profile`, prompts for the new token, verifies it
*before* writing, and does **not** prompt for or fetch the schema. `--new` and
`--rotate` are mutually exclusive.

## Rename / set default / remove

```sh
nsc profiles rename old-name new-name        # also moves ~/.nsc/cache/old-name → cache/new-name
nsc profiles set-default lab
nsc profiles remove staging                  # purges the cache for that profile
nsc profiles remove default                  # refuses unless --force; set a successor first
```

## Token storage

The default is **plaintext** in `config.yaml` (with a one-time warning per session).
For secrets you don't want on disk, use **env-var indirection**:

```yaml
profiles:
  prod:
    name: prod
    url: https://netbox.example.com
    token: !env NSC_PROD_TOKEN
```

Then `export NSC_PROD_TOKEN=…` in your shell rc or load it from a secrets manager
at session start. Keyring-backed storage is on the post-1.0 roadmap.

## Editing the file directly

```sh
nsc config path                              # prints ~/.nsc/config.yaml
nsc config get profiles.prod.url
nsc config set defaults.page_size 100
nsc config edit                              # opens $EDITOR
```

`config set` round-trips through `ruamel.yaml` so comments and the `!env` tags survive.

## Per-invocation overrides

```sh
nsc --profile lab dcim devices list                          # use a non-default profile
nsc --url https://other --token $TOK dcim devices list       # one-off, no config needed
NSC_URL=https://other NSC_TOKEN=$TOK nsc dcim devices list   # env vars also work
```

Override precedence (highest first): CLI flag > env var > config profile.
