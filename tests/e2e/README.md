# Live-NetBox e2e suite (Phase 3d)

These tests exercise `nsc` against a real NetBox 4.5.9 container instead of
mocked HTTP. They are gated out of the default `just test` invocation
(`NSC_E2E=1` required) and require Docker to run.

## Why we don't use `SUPERUSER_API_TOKEN`

The Phase 3 design (`docs/superpowers/specs/2026-05-01-netbox-super-cli-phase-3-design.md` §8.2)
originally assumed the well-known `SUPERUSER_API_TOKEN=<40-hex>` env var would
install a deterministic, hard-coded API token at container startup. That
assumption no longer holds on NetBox 4.5+:

1. **NetBox 4.5+ defaults to v2 tokens.** v2 tokens have a 12-character
   randomly-generated id and a separate plaintext secret. Both halves are
   hashed with a configured pepper before storage. The bootstrap process
   prints only the id (`💡 ... API Token: P5AEcVnCL0fT (use with 'Bearer
   nbt_P5AEcVnCL0fT.<Your token>')`), never the secret. So the value of
   `SUPERUSER_API_TOKEN` is effectively ignored and the secret half is
   unrecoverable.
2. **v2 tokens additionally require `API_TOKEN_PEPPERS` to be configured**
   (the netbox-docker image reads `API_TOKEN_PEPPER_1`, `API_TOKEN_PEPPER_2`,
   ... and assembles the dict). Each pepper must be ≥50 characters; without
   them startup logs `⚠️ No API token will be created as API_TOKEN_PEPPERS is
   not set` and every authenticated request fails with `Invalid v1 token`.

NetBox 4.5+ still **accepts** v1 tokens for authentication
(`netbox/api/authentication.py` keeps both `Token` and `Bearer` keywords);
it just doesn't bootstrap them automatically anymore. So Phase 3d's
workaround:

- We do **not** set `SUPERUSER_API_TOKEN` or `API_TOKEN_PEPPER_1` in
  `docker-compose.yml`. Both were red herrings — the env vars exist, but
  neither lets us pin the v2 secret.
- After `wait_for_netbox.sh` confirms Django is serving the unauthenticated
  login page, it runs a one-line `docker exec ... manage.py shell -c "..."`
  that wipes the admin user's tokens and inserts a v1 token with the
  hard-coded plaintext `0123456789abcdef0123456789abcdef01234567`.
- The CLI under test (`nsc/http/client.py`) sends `Authorization: Token <40-hex>`,
  matching the v1 plaintext lookup path
  (`Token.objects.get(version=1, plaintext=plaintext)`).

This keeps the spec's UX (deterministic token, hard-coded in one place) but
moves the token-installation step from "compose env var" to "post-startup
docker-exec." The mechanism is contained entirely in `wait_for_netbox.sh`;
no Python source under `nsc/` or any test code knows or cares which path
was used.

### When to revisit

Two events would make sense as triggers for revisiting this design:

- **NetBox adds a way to deterministically pin a v2 token at bootstrap**
  (e.g., a `SUPERUSER_API_TOKEN_V2` that takes the full `nbt_<key>.<secret>`
  string and seeds it into the DB). At that point we could drop the
  `docker exec` step from `wait_for_netbox.sh`.
- **`nsc` learns to authenticate with v2 Bearer tokens** (a Phase 4+
  enhancement). At that point we could let the bootstrap generate a random
  v2 token, parse it out of the container logs, and stop creating a v1
  fixture token entirely.

Until either of those happens, the `docker exec` token-install in
`wait_for_netbox.sh` is the cleanest path to "deterministic auth in CI
against NetBox 4.5.9." See `docs/superpowers/specs/2026-05-01-netbox-super-cli-phase-3-design.md` §8.2 for the original spec.
