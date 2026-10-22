# OS keyring storage

`nsc` can keep a profile's API token in your operating system's keyring
(macOS Keychain, Secret Service / libsecret on Linux, Windows Credential
Manager) instead of in `~/.nsc/config.yaml`. The config file then holds only a
`!keyring NAME` reference — the counterpart of the
[`!env NAME` indirection](managing-profiles.md#token-storage).

```yaml
profiles:
  prod:
    url: https://netbox.example.com
    token: !keyring prod
```

## Storing a token

`nsc login` writes the token to the keyring and the reference to the config in
one step. The token is prompted with hidden input, verified against NetBox
first, and never written to disk in plaintext.

```sh
nsc login --new --profile prod --url https://netbox.example.com --store keyring
nsc login --new --profile prod --url https://netbox.example.com \
  --store keyring --keyring-name my-token          # choose the entry name
nsc login --rotate --profile prod --store keyring  # move an existing profile into the keyring
```

| Option | Default |
|---|---|
| `--store keyring` | `--new`: plaintext unless given. `--rotate`: keyring if the profile already uses `!keyring`, otherwise plaintext. |
| `--keyring-name NAME` | The existing `!keyring` name on `--rotate`, otherwise the profile name. |

Rotating a profile that already uses `!keyring` updates the keyring entry in
place, and the config file is left as it is.

## How entries are named

Every entry uses the service name **`nsc`**, and the `NAME` from the tag is
the keyring *username*. `!keyring prod` therefore maps to
`(service="nsc", username="prod")`. To inspect or seed an entry by hand, use
the `keyring` CLI that ships with the dependency:

```sh
keyring get nsc prod
keyring set nsc prod          # prompts for the secret
keyring del nsc prod
```

With the entry seeded this way, you can also write `token: !keyring prod` into
the config yourself (`nsc config edit`).

## When the keyring is read

`!keyring` references are resolved **lazily**. The keyring is read only when a
command actually needs the token, such as an API request, `nsc login`, or
the live-hash check in `nsc cache prune`. Shell completion, `nsc config`, and `nsc profiles`
never touch the keyring, so an unavailable keyring does not break them.

The usual override order still applies: `--token` and `NSC_TOKEN` take priority,
and when either is set the keyring is never read.

## Errors

A missing entry or a missing keyring backend produces a `config` error envelope
(exit code 12) rather than a traceback. The envelope's `details.keyring_name`
names the entry (abridged):

```json
{"error": "no OS keyring entry 'prod' (service 'nsc') for profile 'prod'; store one with `nsc login --rotate --profile prod --store keyring`.", "type": "config", "details": {"keyring_name": "prod"}}
```

Headless machines such as CI runners, containers, and SSH sessions without a
desktop session often have **no usable backend**. Use `!env` indirection
there, or install a backend such as
[`keyrings.alt`](https://pypi.org/project/keyrings.alt/) into the same
environment as `nsc`. You can force a backend with the standard
`PYTHON_KEYRING_BACKEND` environment variable.
