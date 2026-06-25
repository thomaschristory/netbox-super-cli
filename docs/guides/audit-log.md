# Audit log

Every write request and response is appended to `~/.nsc/logs/audit.jsonl` (one
JSON object per line), including dry-runs (flagged so you can tell they were
never sent). The file is created owner-only (`0600`) inside a `0700` directory,
so a co-located user on a shared host cannot read your mutations.

## Redaction modes

The `audit_redaction` setting under `defaults` in `~/.nsc/config.yaml` chooses
how much of each exchange is written:

```yaml
defaults:
  audit_redaction: safe   # default; or: full
```

| Mode | What lands in `audit.jsonl` |
| --- | --- |
| `safe` (default) | Full request/response records, with known secrets masked to `<redacted>`. |
| `full` | Routing metadata only — no body, header, or query content at all. |

### `safe` — redact known secrets

The default. The complete exchange is logged so you can debug what was sent and
what NetBox returned, but sensitive values are masked **before write**:

- A field is sensitive if its OpenAPI schema has `format: password` OR its name
  (case-insensitive) is `password`, `secret`, `token`, `api_key`, `apikey`,
  `private_key`, `passphrase`, or `client_secret`. Top-level and nested fields
  are masked; arrays of objects are masked per-element.
- Sensitive **headers** (`Authorization`, `Cookie`, `Set-Cookie`, `X-API-Key`,
  `Proxy-Authorization`) are masked on both request and response.
- **Not** masked: the endpoint URL, query string, non-sensitive headers, and
  **response bodies** (NetBox's response is recorded as-is — if it echoes back a
  secret, that is NetBox's bug). This is the residual exposure `full` closes.

### `full` — routing metadata only

For compliance-sensitive deployments. Every body is **omitted entirely** (not
truncated), regardless of shape or size — small JSON, large JSON, error
envelopes, and multipart payloads all collapse to nothing. Each audit line
contains exactly five keys:

```json
{"method":"POST","url":"https://nb/api/users/users/","status_code":201,"timestamp":"2026-06-25T12:00:00.000Z","profile":"prod"}
```

Nothing else is written: no request body, no response body, and no headers. The
one remaining string — `url` — is sanitized to scheme + host + path before it is
logged: the **query string is dropped** (a debug-mode GET can encode a
`private_key` or similar filter value there) and any **`user:pass@` userinfo is
stripped** (a `https://user:pass@host` profile URL would otherwise carry basic-auth
credentials). So no field can carry a secret into the log.

## Trade-offs

| | `safe` | `full` |
| --- | --- | --- |
| Debugging | Easy — you can see the payload and the server response. | Hard — you only know *that* a call happened, not its contents. |
| Compliance | Good for the common case; response bodies are unredacted. | Strictest; no body data ever persisted. |
| Reproducing a failed write | Possible from the recorded body. | Not possible from the log alone. |

Switch to `full` when policy forbids persisting request/response payloads even
in redacted form; otherwise keep the default `safe`, which preserves
debuggability while masking known secrets.

## Backward compatibility

`safe` is the default and is unchanged. Existing configs — whether they set
`audit_redaction: safe` or omit the key entirely — behave exactly as before.
