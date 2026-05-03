"""Phase 4d: 512-byte stdin sniffer disambiguating JSON-array / NDJSON / single-JSON / YAML."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from nsc.cli.writes.input import InputError, NDJSONParseError, collect


def _read(text: str) -> tuple[list[dict[str, object]], bool]:
    raw = collect(file=Path("-"), fields=[], stdin=io.StringIO(text))
    return raw.records, raw.is_explicit_list


def test_stdin_json_array_parses_as_list() -> None:
    records, is_list = _read('[{"name": "a"}, {"name": "b"}]')
    assert [r["name"] for r in records] == ["a", "b"]
    assert is_list is True


def test_stdin_single_json_object_parses_as_one_record() -> None:
    records, is_list = _read('{"name": "alpha"}')
    assert records == [{"name": "alpha"}]
    assert is_list is False


def test_stdin_ndjson_two_objects_one_per_line() -> None:
    records, is_list = _read('{"name": "a"}\n{"name": "b"}\n')
    assert [r["name"] for r in records] == ["a", "b"]
    assert is_list is True


def test_stdin_ndjson_with_leading_whitespace() -> None:
    records, is_list = _read('  \n  {"name": "a"}\n{"name": "b"}\n')
    assert [r["name"] for r in records] == ["a", "b"]
    assert is_list is True


def test_stdin_yaml_block_falls_through_to_yaml() -> None:
    records, is_list = _read("name: alpha\nslug: a\n")
    assert records == [{"name": "alpha", "slug": "a"}]
    assert is_list is False


def test_stdin_flow_yaml_with_curly_still_works() -> None:
    # Single-line flow YAML that starts with `{` but is not NDJSON.
    records, _ = _read("{name: alpha, slug: a}")
    assert records == [{"name": "alpha", "slug": "a"}]


def test_stdin_ndjson_bad_line_raises_ndjson_parse_error() -> None:
    with pytest.raises(NDJSONParseError) as exc_info:
        _read('{"name": "a"}\nnot json\n{"name": "c"}\n')
    assert exc_info.value.bad_lines[0]["line"] == 2


def test_stdin_empty_is_input_error() -> None:
    with pytest.raises(InputError):
        _read("")


def test_stdin_whitespace_only_is_input_error() -> None:
    with pytest.raises(InputError):
        _read("   \n\n  ")
