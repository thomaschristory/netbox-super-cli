"""Phase 3d — bad token surfaces as `auth` envelope, exit 8."""

from __future__ import annotations

import json


def test_bad_token_returns_auth_envelope(run_nsc) -> None:
    r = run_nsc(
        "extras",
        "tags",
        "list",
        "--output",
        "json",
        env={"NSC_TOKEN": "0000000000000000000000000000000000000000"},
    )
    assert r.returncode == 8, (r.returncode, r.stdout, r.stderr)

    envelope = json.loads(r.stdout)
    assert envelope["type"] == "auth"
    # status_code is whatever NetBox returns — usually 403 with token auth,
    # 401 in some plugin paths.
    assert envelope["status_code"] in (401, 403)
