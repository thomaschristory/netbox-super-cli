"""Phase 4d: NDJSON parser and extension routing in writes/input.py."""

from __future__ import annotations

import gzip
import json as _json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from typer.testing import CliRunner

from nsc.cli.app import app
from nsc.cli.writes.input import (
    InputError,
    NDJSONParseError,
    collect,
)


def test_ndjson_extension_parses_one_record_per_line(tmp_path: Path) -> None:
    p = tmp_path / "devices.ndjson"
    p.write_text('{"name": "a"}\n{"name": "b"}\n{"name": "c"}\n', encoding="utf-8")
    raw = collect(file=p, fields=[], stdin=None)
    assert raw.records == [{"name": "a"}, {"name": "b"}, {"name": "c"}]
    assert raw.is_explicit_list is True
    assert raw.source == "file"
    assert raw.file_path == p


def test_jsonl_extension_is_synonym(tmp_path: Path) -> None:
    p = tmp_path / "tags.jsonl"
    p.write_text('{"name": "x"}\n{"name": "y"}\n', encoding="utf-8")
    raw = collect(file=p, fields=[], stdin=None)
    assert [r["name"] for r in raw.records] == ["x", "y"]


def test_ndjson_blank_lines_skipped(tmp_path: Path) -> None:
    p = tmp_path / "f.ndjson"
    p.write_text('{"name": "a"}\n\n  \n{"name": "b"}\n', encoding="utf-8")
    raw = collect(file=p, fields=[], stdin=None)
    assert [r["name"] for r in raw.records] == ["a", "b"]


def test_ndjson_crlf_endings_supported(tmp_path: Path) -> None:
    p = tmp_path / "f.ndjson"
    p.write_bytes(b'{"name": "a"}\r\n{"name": "b"}\r\n')
    raw = collect(file=p, fields=[], stdin=None)
    assert [r["name"] for r in raw.records] == ["a", "b"]


def test_ndjson_one_bad_line_aborts_entire_batch(tmp_path: Path) -> None:
    p = tmp_path / "f.ndjson"
    p.write_text('{"name": "a"}\n{not valid json\n{"name": "c"}\n', encoding="utf-8")
    with pytest.raises(NDJSONParseError) as exc_info:
        collect(file=p, fields=[], stdin=None)
    assert len(exc_info.value.bad_lines) == 1
    assert exc_info.value.bad_lines[0]["line"] == 2
    assert isinstance(exc_info.value.bad_lines[0]["reason"], str)


def test_ndjson_non_mapping_line_is_a_bad_line(tmp_path: Path) -> None:
    p = tmp_path / "f.ndjson"
    p.write_text('{"name": "a"}\n[1, 2]\n42\n"hello"\n', encoding="utf-8")
    with pytest.raises(NDJSONParseError) as exc_info:
        collect(file=p, fields=[], stdin=None)
    lines = [bl["line"] for bl in exc_info.value.bad_lines]
    assert lines == [2, 3, 4]


def test_ndjson_bad_lines_capped_at_20(tmp_path: Path) -> None:
    p = tmp_path / "f.ndjson"
    bad = "not json\n" * 50
    p.write_text(bad, encoding="utf-8")
    with pytest.raises(NDJSONParseError) as exc_info:
        collect(file=p, fields=[], stdin=None)
    assert len(exc_info.value.bad_lines) == 20
    # The first 20 line numbers, not the last 20.
    assert [bl["line"] for bl in exc_info.value.bad_lines] == list(range(1, 21))


def test_ndjson_empty_file_is_an_input_error(tmp_path: Path) -> None:
    p = tmp_path / "f.ndjson"
    p.write_text("", encoding="utf-8")
    with pytest.raises(InputError) as exc_info:
        collect(file=p, fields=[], stdin=None)
    assert "no records" in str(exc_info.value).lower() or "empty" in str(exc_info.value).lower()


def test_ndjson_only_blank_lines_is_an_input_error(tmp_path: Path) -> None:
    p = tmp_path / "f.ndjson"
    p.write_text("\n\n  \n", encoding="utf-8")
    with pytest.raises(InputError):
        collect(file=p, fields=[], stdin=None)


def test_ndjson_subclass_of_input_error() -> None:
    # Callers that already catch InputError still see NDJSONParseError.
    assert issubclass(NDJSONParseError, InputError)


def test_unsupported_extension_still_rejected(tmp_path: Path) -> None:
    p = tmp_path / "f.txt"
    p.write_text('{"name": "a"}', encoding="utf-8")
    with pytest.raises(InputError) as exc_info:
        collect(file=p, fields=[], stdin=None)
    assert ".ndjson" in str(exc_info.value) or "unsupported" in str(exc_info.value).lower()


# --- handler integration ---


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


def test_handler_emits_input_error_envelope_on_ndjson_parse_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture_profile_yaml: Path,
) -> None:
    """Spec §4.4: parse failure aborts before any wire request and emits
    `type: input_error` (exit 4) with `details.bad_lines`.
    """
    monkeypatch.setenv("NSC_HOME", str(fixture_profile_yaml))

    p = tmp_path / "bad.ndjson"
    p.write_text('{"name": "a"}\nnot json\n{"name": "c"}\n', encoding="utf-8")

    with respx.mock(assert_all_called=False) as router:
        _mock_schema(router)
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["dcim", "devices", "create", "-f", str(p), "--apply", "--output", "json"],
        )
        # Spec: no wire write request before parse-abort. The schema fetch is OK.
        write_calls = [c for c in router.calls if c.request.method != "GET"]
        assert write_calls == []

    assert result.exit_code == 4, (result.stdout, result.stderr)
    payload = _json.loads(result.stdout)
    assert payload["type"] == "input_error"
    assert payload["details"]["bad_lines"][0]["line"] == 2
