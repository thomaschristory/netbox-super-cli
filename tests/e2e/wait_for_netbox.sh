#!/usr/bin/env bash
# Bring NetBox to an "e2e-ready" state. Two phases:
#
# 1. Wait until Django is serving the unauthenticated login page at $NSC_URL/login/
#    (proxy for "migrations and gunicorn are up"). 5-minute deadline; cold-start
#    of NetBox 4.5.9 takes ~90–180 s on CI.
# 2. Create a deterministic v1 admin API token via `docker exec`, replacing any
#    previously-bootstrapped token. Required because NetBox 4.5+ generates a
#    random v2 token at bootstrap and never reveals the secret half — the
#    spec's hardcoded fixture token cannot be installed via SUPERUSER_API_TOKEN
#    on this version. See tests/e2e/README.md for the full rationale.
#
# Exit 0 when both phases succeed; 1 on timeout or token-create failure.

set -euo pipefail

URL="${NSC_URL:-http://127.0.0.1:8080}"
TOKEN="${NSC_TOKEN:-0123456789abcdef0123456789abcdef01234567}"
CONTAINER="${NSC_E2E_CONTAINER:-e2e-netbox-1}"
DEADLINE=$(( $(date +%s) + 300 ))

# Phase 1: poll the unauthenticated login page until we get a 2xx.
while true; do
    if curl -fsS -m 3 "${URL}/login/" >/dev/null 2>&1; then
        echo "django up: ${URL}/login/"
        break
    fi
    if [ "$(date +%s)" -ge "$DEADLINE" ]; then
        echo "netbox did not become ready within 5 minutes" >&2
        exit 1
    fi
    echo "waiting for ${URL}/login/ ..."
    sleep 5
done

# Phase 2: create a deterministic v1 admin token. Idempotent: any pre-existing
# admin tokens are deleted first, so re-running this script after a partial
# previous run cleanly resets the auth state.
docker exec "${CONTAINER}" /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell -c "
from users.models import Token, User
admin = User.objects.get(username='admin')
admin.tokens.all().delete()
t = Token(user=admin, version=1, token='${TOKEN}', description='nsc e2e fixture')
t.full_clean()
t.save()
print('TOKEN_INSTALLED', t.plaintext)
" >/tmp/nsc-e2e-token-install.log 2>&1 || {
    echo "failed to install e2e token; container log follows:" >&2
    cat /tmp/nsc-e2e-token-install.log >&2
    exit 1
}

# Confirm the token actually authenticates (catches typos in either phase).
if ! curl -fsS -m 5 -H "Authorization: Token ${TOKEN}" "${URL}/api/status/" >/dev/null 2>&1; then
    echo "token install reported success but /api/status/ still rejects the token" >&2
    exit 1
fi

echo "netbox e2e-ready: ${URL} (v1 token installed)"
