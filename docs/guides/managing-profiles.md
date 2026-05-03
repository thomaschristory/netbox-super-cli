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
the same verification (`GET /api/users/tokens/?limit=1`) before persisting.
Refuses if `lab` already exists.

## Add a profile interactively

```sh
nsc init                                                              # first time, no config yet
nsc login --new --profile staging --url https://netbox-staging.local  # subsequent profiles
```

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
