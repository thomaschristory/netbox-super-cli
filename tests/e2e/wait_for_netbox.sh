#!/usr/bin/env bash
# Block until NetBox is responsive at http://127.0.0.1:8080/api/status/.
# 5-minute deadline (cold-start migration of NetBox 4.5.9 takes ~90–180s on CI).
# Exit 0 on success, 1 on timeout. Stdout reports each attempt.

set -euo pipefail

URL="${NSC_URL:-http://127.0.0.1:8080}/api/status/"
DEADLINE=$(( $(date +%s) + 300 ))

while true; do
    if curl -fsS -m 3 "$URL" >/dev/null 2>&1; then
        echo "netbox ready: $URL"
        exit 0
    fi
    if [ "$(date +%s)" -ge "$DEADLINE" ]; then
        echo "netbox did not become ready within 5 minutes" >&2
        exit 1
    fi
    echo "waiting for $URL ..."
    sleep 5
done
