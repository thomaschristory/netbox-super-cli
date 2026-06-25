# Install

`nsc` is a single Python package, two entry points (`nsc` and `netbox-super-cli`).

## Recommended: pipx or uv tool

The CLI is a stand-alone tool, not a library — install it isolated from your
project Python environments.

```sh
# pipx
pipx install netbox-super-cli

# uv (faster, recommended if you already use uv elsewhere)
uv tool install netbox-super-cli
```

Verify the install:

```sh
nsc --version
nsc --help
```

## From source

```sh
git clone https://github.com/thomaschristory/netbox-super-cli
cd netbox-super-cli
uv sync
uv run nsc --version
```

## Shell completion

`nsc` ships static completion stubs for bash, zsh, fish, and PowerShell. Auto-detect:

```sh
nsc --install-completion         # detects $SHELL
```

Or pick the shell explicitly:

```sh
nsc --install-completion=bash
nsc --install-completion=zsh
nsc --install-completion=fish
nsc --install-completion=pwsh
```

Restart your shell, then verify with `nsc <TAB><TAB>`.

### Dynamic completion

Once completion is installed, TAB expands real values from the cached schema —
no network call at TAB time:

```sh
nsc ls dev<TAB>                  # → devices device-roles device-types
nsc --profile <TAB>             # → profile names from ~/.nsc/config.yaml
nsc dcim devices list --status <TAB>   # → schema enum values for that filter
```

## Requirements

- Python ≥ 3.12.
- A reachable NetBox install (any version with `/api/schema/` enabled — 4.5+).
- A NetBox API token (read-only is enough for read commands; writable for `--apply`).
