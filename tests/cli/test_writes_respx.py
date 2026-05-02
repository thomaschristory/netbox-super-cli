"""Write-side respx integration suite (Phase 3b)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from typer.testing import CliRunner

from nsc.cli.app import app
from nsc.output.errors import EXIT_CODES, ErrorType


@pytest.fixture(autouse=True)
def _bundled_schema_for_runtime(
    monkeypatch: pytest.MonkeyPatch, fixture_profile_yaml: Path
) -> None:
    monkeypatch.setenv("NSC_HOME", str(fixture_profile_yaml))


def _mock_schema(respx_mock: Any) -> None:
    bundled = next(Path("nsc/schemas/bundled").glob("*.json*"))
    body = (
        gzip.decompress(bundled.read_bytes())
        if bundled.name.endswith(".gz")
        else bundled.read_bytes()
    )
    respx_mock.get("https://nb.example/api/schema/?format=json").mock(
        return_value=httpx.Response(200, content=body, headers={"content-type": "application/json"})
    )


def _payload(tmp_path: Path, body: dict[str, Any] | list[dict[str, Any]]) -> Path:
    p = tmp_path / "body.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def _audit_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixture_profile_yaml: Path
) -> Path:
    """Create a fresh NSC_HOME under tmp_path with the standard test profile."""
    home = tmp_path / "audit_home"
    home.mkdir()
    (home / "config.yaml").write_text(
        (fixture_profile_yaml / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setenv("NSC_HOME", str(home))
    return home


# The bundled NetBox `dcim_devices_create` schema requires `device_type`, `role`,
# and `site`; preflight rejects payloads missing any of these. The valid-create
# tests below provide all three so preflight passes and the request reaches respx.
_VALID_DEVICE: dict[str, Any] = {
    "name": "rack-01",
    "device_type": 1,
    "role": 1,
    "site": 1,
}


@respx.mock
def test_create_dry_run_does_not_send(tmp_path: Path) -> None:
    _mock_schema(respx.mock)
    route = respx.post("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(201, json={"id": 1})
    )
    payload = _payload(tmp_path, _VALID_DEVICE)
    result = CliRunner().invoke(
        app,
        ["dcim", "devices", "create", "-f", str(payload), "--output", "json"],
    )
    assert result.exit_code in (0, 4), result.stdout
    assert route.call_count == 0  # nothing sent on dry-run


@respx.mock
def test_create_apply_sends_post(tmp_path: Path) -> None:
    _mock_schema(respx.mock)
    route = respx.post("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(201, json={"id": 1, "name": "rack-01"})
    )
    payload = _payload(tmp_path, _VALID_DEVICE)
    result = CliRunner().invoke(
        app,
        ["dcim", "devices", "create", "-f", str(payload), "--apply", "--output", "json"],
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert route.call_count == 1
    body = json.loads(route.calls.last.request.content)
    assert body == _VALID_DEVICE


@respx.mock
def test_create_apply_validation_error_from_server_maps_to_validation_envelope(
    tmp_path: Path,
) -> None:
    _mock_schema(respx.mock)
    respx.post("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(400, json={"name": ["This field may not be blank."]})
    )
    payload = _payload(tmp_path, _VALID_DEVICE)
    result = CliRunner().invoke(
        app,
        ["dcim", "devices", "create", "-f", str(payload), "--apply", "--output", "json"],
    )
    assert result.exit_code == EXIT_CODES[ErrorType.VALIDATION]
    parsed = json.loads(result.stdout)
    assert parsed["type"] == "validation"
    assert parsed["status_code"] == 400


@respx.mock
def test_create_apply_conflict_409(tmp_path: Path) -> None:
    _mock_schema(respx.mock)
    respx.post("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(409, json={"detail": "duplicate"})
    )
    payload = _payload(tmp_path, _VALID_DEVICE)
    result = CliRunner().invoke(
        app,
        ["dcim", "devices", "create", "-f", str(payload), "--apply", "--output", "json"],
    )
    assert result.exit_code == EXIT_CODES[ErrorType.CONFLICT]
    parsed = json.loads(result.stdout)
    assert parsed["type"] == "conflict"


@respx.mock
def test_create_apply_auth_401(tmp_path: Path) -> None:
    _mock_schema(respx.mock)
    respx.post("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(401, json={"detail": "Invalid token."})
    )
    payload = _payload(tmp_path, _VALID_DEVICE)
    result = CliRunner().invoke(
        app,
        ["dcim", "devices", "create", "-f", str(payload), "--apply", "--output", "json"],
    )
    assert result.exit_code == EXIT_CODES[ErrorType.AUTH]
    parsed = json.loads(result.stdout)
    assert parsed["type"] == "auth"


@respx.mock
def test_update_apply_sends_patch(tmp_path: Path) -> None:
    _mock_schema(respx.mock)
    route = respx.patch("https://nb.example/api/dcim/devices/42/").mock(
        return_value=httpx.Response(200, json={"id": 42, "status": "decommissioning"})
    )
    result = CliRunner().invoke(
        app,
        [
            "dcim",
            "devices",
            "update",
            "42",
            "--field",
            "status=decommissioning",
            "--apply",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert route.call_count == 1
    body = json.loads(route.calls.last.request.content)
    assert body == {"status": "decommissioning"}


@respx.mock
def test_delete_apply_204_returns_deleted_true() -> None:
    _mock_schema(respx.mock)
    respx.delete("https://nb.example/api/dcim/devices/42/").mock(return_value=httpx.Response(204))
    result = CliRunner().invoke(
        app,
        ["dcim", "devices", "delete", "42", "--apply", "--output", "json"],
    )
    assert result.exit_code == 0, result.stdout
    parsed = json.loads(result.stdout)
    assert parsed == {"deleted": True}


@respx.mock
def test_delete_apply_404_default_returns_already_absent() -> None:
    _mock_schema(respx.mock)
    respx.delete("https://nb.example/api/dcim/devices/42/").mock(
        return_value=httpx.Response(404, json={"detail": "Not found."})
    )
    result = CliRunner().invoke(
        app,
        ["dcim", "devices", "delete", "42", "--apply", "--output", "json"],
    )
    assert result.exit_code == 0, result.stdout
    parsed = json.loads(result.stdout)
    assert parsed == {"deleted": False, "reason": "already_absent"}


@respx.mock
def test_delete_apply_404_strict_returns_not_found_envelope() -> None:
    _mock_schema(respx.mock)
    respx.delete("https://nb.example/api/dcim/devices/42/").mock(
        return_value=httpx.Response(404, json={"detail": "Not found."})
    )
    result = CliRunner().invoke(
        app,
        ["dcim", "devices", "delete", "42", "--apply", "--strict", "--output", "json"],
    )
    assert result.exit_code == EXIT_CODES[ErrorType.NOT_FOUND]
    parsed = json.loads(result.stdout)
    assert parsed["type"] == "not_found"


@respx.mock
def test_create_preflight_failure_short_circuits_with_exit_4(tmp_path: Path) -> None:
    _mock_schema(respx.mock)
    route = respx.post("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(201, json={"id": 1})
    )
    # Missing required `name` — preflight should fail before --apply touches the wire.
    payload = _payload(tmp_path, {"comments": "no name"})
    result = CliRunner().invoke(
        app,
        ["dcim", "devices", "create", "-f", str(payload), "--apply", "--output", "json"],
    )
    assert result.exit_code == EXIT_CODES[ErrorType.VALIDATION]
    assert route.call_count == 0


@respx.mock
def test_create_all_flag_refused(tmp_path: Path) -> None:
    _mock_schema(respx.mock)
    payload = _payload(tmp_path, {"name": "x"})
    # `--all` is not a flag on write commands. Typer/click rejects unknown
    # flags with usage error (exit 2). This documents that the read-side
    # `--all` is NOT visible on writes.
    result = CliRunner().invoke(
        app,
        ["dcim", "devices", "create", "-f", str(payload), "--all", "--apply"],
    )
    assert result.exit_code != 0


@respx.mock
def test_explain_renders_resolved_request(tmp_path: Path) -> None:
    _mock_schema(respx.mock)
    payload = _payload(tmp_path, _VALID_DEVICE)
    result = CliRunner().invoke(
        app,
        [
            "dcim",
            "devices",
            "create",
            "-f",
            str(payload),
            "--explain",
            "--output",
            "json",
        ],
    )
    assert result.exit_code in (0, 4), result.stdout
    parsed = json.loads(result.stdout)
    assert parsed["operation_id"] == "dcim_devices_create"
    assert parsed["requests"][0]["method"] == "POST"


@respx.mock
def test_create_apply_writes_audit_jsonl_and_last_request_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_profile_yaml: Path,
) -> None:
    home = tmp_path / "audit_home"
    home.mkdir()
    (home / "config.yaml").write_text(
        (fixture_profile_yaml / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setenv("NSC_HOME", str(home))
    _mock_schema(respx.mock)
    respx.post("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(201, json={"id": 1})
    )
    payload = _payload(tmp_path, _VALID_DEVICE)
    result = CliRunner().invoke(
        app,
        ["dcim", "devices", "create", "-f", str(payload), "--apply", "--output", "json"],
    )
    assert result.exit_code == 0, result.stdout
    audit = (home / "logs" / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(audit) == 1
    last = json.loads((home / "logs" / "last-request.json").read_text(encoding="utf-8"))
    assert last["method"] == "POST"
    assert last["request"]["body"] == _VALID_DEVICE
    assert last["request"]["headers"]["Authorization"] == "<redacted>"


@respx.mock
def test_dry_run_does_not_overwrite_last_request_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_profile_yaml: Path,
) -> None:
    home = tmp_path / "audit_home"
    home.mkdir()
    (home / "config.yaml").write_text(
        (fixture_profile_yaml / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setenv("NSC_HOME", str(home))
    _mock_schema(respx.mock)
    payload = _payload(tmp_path, _VALID_DEVICE)
    CliRunner().invoke(app, ["dcim", "devices", "create", "-f", str(payload), "--output", "json"])
    audit = (home / "logs" / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(audit) == 1
    assert json.loads(audit[0])["dry_run"] is True
    assert not (home / "logs" / "last-request.json").exists()


# ---------------------------------------------------------------------------
# Phase 3c: bulk routing, sequential loop, on-error semantics (spec §7.3)
# ---------------------------------------------------------------------------


def _bulk_records(n: int) -> list[dict[str, Any]]:
    """N valid device payloads (each carries the required fields).

    The bundled `dcim_devices_create` schema requires `device_type`, `role`,
    and `site`; these tests need preflight to pass so the request reaches
    respx.
    """
    return [{"name": f"r-{i}", "device_type": 1, "role": 1, "site": 1} for i in range(n)]


@respx.mock
def test_bulk_create_5_records_sends_one_post_with_array_body(tmp_path: Path) -> None:
    _mock_schema(respx.mock)
    route = respx.post("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(201, json=[{"id": i} for i in range(5)])
    )
    payload = _payload(tmp_path, _bulk_records(5))
    result = CliRunner().invoke(
        app,
        ["dcim", "devices", "create", "-f", str(payload), "--apply", "--output", "json"],
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert route.call_count == 1
    sent = json.loads(route.calls.last.request.content)
    assert isinstance(sent, list)
    assert [item["name"] for item in sent] == [f"r-{i}" for i in range(5)]


@respx.mock
def test_no_bulk_5_records_sends_5_sequential_posts(tmp_path: Path) -> None:
    _mock_schema(respx.mock)
    route = respx.post("https://nb.example/api/dcim/devices/").mock(
        return_value=httpx.Response(201, json={"id": 1})
    )
    payload = _payload(tmp_path, _bulk_records(5))
    result = CliRunner().invoke(
        app,
        [
            "dcim",
            "devices",
            "create",
            "-f",
            str(payload),
            "--apply",
            "--no-bulk",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert route.call_count == 5


@respx.mock
def test_loop_stop_on_third_record_400_returns_partial_progress(tmp_path: Path) -> None:
    _mock_schema(respx.mock)
    call_count = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 3:
            return httpx.Response(400, json={"name": ["bad"]})
        return httpx.Response(201, json={"id": call_count["n"]})

    respx.post("https://nb.example/api/dcim/devices/").mock(side_effect=responder)
    payload = _payload(tmp_path, _bulk_records(5))
    result = CliRunner().invoke(
        app,
        [
            "dcim",
            "devices",
            "create",
            "-f",
            str(payload),
            "--apply",
            "--no-bulk",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == EXIT_CODES[ErrorType.VALIDATION]
    parsed = json.loads(result.stdout)
    assert parsed["type"] == "validation"
    assert parsed["record_index"] == 2
    assert parsed["details"]["partial_progress"] == {
        "success": 2,
        "failed": 1,
        "remaining": 2,
    }
    assert parsed["details"]["on_error"] == "stop"


@respx.mock
def test_loop_continue_with_two_failures_returns_summary_envelope(tmp_path: Path) -> None:
    _mock_schema(respx.mock)
    call_count = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(400, json={"name": ["bad first"]})
        if call_count["n"] == 3:
            return httpx.Response(401, json={"detail": "no auth"})
        return httpx.Response(201, json={"id": call_count["n"]})

    respx.post("https://nb.example/api/dcim/devices/").mock(side_effect=responder)
    payload = _payload(tmp_path, _bulk_records(5))
    result = CliRunner().invoke(
        app,
        [
            "dcim",
            "devices",
            "create",
            "-f",
            str(payload),
            "--apply",
            "--no-bulk",
            "--on-error",
            "continue",
            "--output",
            "json",
        ],
    )
    # validation > auth (per ERROR_TYPE_PRECEDENCE) → exit 4
    assert result.exit_code == EXIT_CODES[ErrorType.VALIDATION]
    parsed = json.loads(result.stdout)
    assert parsed["type"] == "validation"
    assert parsed["details"]["on_error"] == "continue"
    assert parsed["details"]["partial_progress"] == {
        "success": 3,
        "failed": 2,
        "remaining": 0,
    }
    failures = parsed["details"]["failures"]
    indices = sorted(f["record_index"] for f in failures)
    assert indices == [0, 2]
    types = {f["type"] for f in failures}
    assert types == {"validation", "auth"}


@respx.mock
def test_loop_audit_log_has_one_entry_per_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_profile_yaml: Path,
) -> None:
    home = _audit_home(tmp_path, monkeypatch, fixture_profile_yaml)
    _mock_schema(respx.mock)
    call_count = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 2:
            return httpx.Response(400, json={"name": ["bad"]})
        return httpx.Response(201, json={"id": call_count["n"]})

    respx.post("https://nb.example/api/dcim/devices/").mock(side_effect=responder)
    payload = _payload(tmp_path, _bulk_records(3))
    CliRunner().invoke(
        app,
        [
            "dcim",
            "devices",
            "create",
            "-f",
            str(payload),
            "--apply",
            "--no-bulk",
            "--on-error",
            "continue",
            "--output",
            "json",
        ],
    )
    audit_path = home / "logs" / "audit.jsonl"
    lines = audit_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3  # one per attempted record
    statuses = [json.loads(line)["error_kind"] for line in lines]
    # NetBoxClient stamps "4xx" for any non-2xx 4xx response on the audit entry.
    assert statuses == [None, "4xx", None]


@respx.mock
def test_bulk_on_non_bulk_endpoint_returns_client_error(tmp_path: Path) -> None:
    """Pick an endpoint whose request_body.top_level is "object" (no array branch).

    The bundled `dcim_devices_partial_update` PATCH endpoint takes a single
    object body. Using PATCH against a single id with --bulk should be refused.
    """
    _mock_schema(respx.mock)
    payload = _payload(tmp_path, [{"status": "active"}])
    result = CliRunner().invoke(
        app,
        [
            "dcim",
            "devices",
            "update",
            "42",
            "-f",
            str(payload),
            "--apply",
            "--bulk",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == EXIT_CODES[ErrorType.CLIENT]
    parsed = json.loads(result.stdout)
    assert parsed["type"] == "client"
    assert parsed["details"]["flag"] == "--bulk"


@respx.mock
def test_bulk_and_no_bulk_together_returns_client_error(tmp_path: Path) -> None:
    _mock_schema(respx.mock)
    payload = _payload(tmp_path, [{"name": "x", "device_type": 1, "role": 1, "site": 1}])
    result = CliRunner().invoke(
        app,
        [
            "dcim",
            "devices",
            "create",
            "-f",
            str(payload),
            "--apply",
            "--bulk",
            "--no-bulk",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == EXIT_CODES[ErrorType.CLIENT]
    parsed = json.loads(result.stdout)
    assert parsed["details"]["flag"] == "--bulk/--no-bulk"


@respx.mock
def test_explain_includes_bulk_reasoning(tmp_path: Path) -> None:
    _mock_schema(respx.mock)
    payload = _payload(tmp_path, _bulk_records(3))
    result = CliRunner().invoke(
        app,
        ["dcim", "devices", "create", "-f", str(payload), "--explain", "--output", "json"],
    )
    # --explain without --apply renders the trace as JSON to stdout.
    parsed = json.loads(result.stdout)
    assert parsed["bulk_reasoning"]
    assert "3" in parsed["bulk_reasoning"]


@respx.mock
def test_dry_run_bulk_writes_one_audit_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_profile_yaml: Path,
) -> None:
    home = _audit_home(tmp_path, monkeypatch, fixture_profile_yaml)
    _mock_schema(respx.mock)
    payload = _payload(tmp_path, _bulk_records(3))
    CliRunner().invoke(
        app,
        ["dcim", "devices", "create", "-f", str(payload), "--output", "json"],
    )
    audit_path = home / "logs" / "audit.jsonl"
    lines = audit_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["dry_run"] is True
    assert entry["record_indices"] == [0, 1, 2]
