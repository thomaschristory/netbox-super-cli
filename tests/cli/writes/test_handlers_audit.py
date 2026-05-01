"""handler-level audit emission (Phase 3b).

End-to-end assertions are in tests/cli/test_writes_respx.py (Task 11). This
test isolates the synthetic-audit-on-dry-run behavior that lives in the handler.
"""

from __future__ import annotations

import json as _json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nsc.cli.app import app


def _setup_home(tmp_path: Path, fixture_profile_yaml: Path) -> Path:
    src = (fixture_profile_yaml / "config.yaml").read_text(encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(src, encoding="utf-8")
    return home


@pytest.mark.skip(reason="depends on Task 10 registering write commands")
def test_dry_run_create_appends_synthetic_audit_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fixture_profile_yaml: Path,
) -> None:
    home = _setup_home(tmp_path, fixture_profile_yaml)
    monkeypatch.setenv("NSC_HOME", str(home))
    # Schema fetched from the bundled fallback — no network needed.
    payload = tmp_path / "device.json"
    payload.write_text('{"name": "rack-01"}', encoding="utf-8")
    # Dry run (no --apply): nothing on the wire; expect audit.jsonl entry anyway.
    result = CliRunner().invoke(
        app,
        [
            "--schema",
            "nsc/schemas/bundled/netbox-4.6.0-beta2.json.gz",
            "dcim",
            "devices",
            "create",
            "-f",
            str(payload),
            "--output",
            "json",
        ],
    )
    assert result.exit_code in (0, 4), (result.stdout, result.stderr)
    audit = (home / "logs" / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(audit) == 1
    entry = _json.loads(audit[0])
    assert entry["dry_run"] is True
    assert entry["applied"] is False
    assert entry["operation_id"] == "dcim_devices_create"
    # last-request.json must NOT be touched on dry-run
    assert not (home / "logs" / "last-request.json").exists()
