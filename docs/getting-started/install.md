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

> Dynamic completion (resource names, profile names, filter keys) is on the
> post-1.0 roadmap.

## Requirements

- Python ≥ 3.12.
- A reachable NetBox install (any version with `/api/schema/` enabled — 4.5+).
- A NetBox API token (read-only is enough for read commands; writable for `--apply`).
