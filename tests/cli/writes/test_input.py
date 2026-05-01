"""writes.input.collect — file/stdin/--field merging (Phase 3b)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from nsc.cli.writes.input import (
    InputError,
    RawWriteInput,
    collect,
)


def test_yaml_file_single_object(tmp_path: Path) -> None:
    p = tmp_path / "device.yaml"
    p.write_text("name: rack-01-sw01\nstatus: active\n", encoding="utf-8")
    result = collect(file=p, fields=[], stdin=None)
    assert isinstance(result, RawWriteInput)
    assert result.records == [{"name": "rack-01-sw01", "status": "active"}]
    assert result.source == "file"
    assert result.file_path == p
    assert result.is_explicit_list is False


def test_json_file_single_object(tmp_path: Path) -> None:
    p = tmp_path / "device.json"
    p.write_text('{"name": "x"}', encoding="utf-8")
    result = collect(file=p, fields=[], stdin=None)
    assert result.records == [{"name": "x"}]
    assert result.source == "file"


def test_stdin_yaml_sniffed(tmp_path: Path) -> None:
    stdin = io.StringIO("name: rack-01\n")
    result = collect(file=Path("-"), fields=[], stdin=stdin)
    assert result.records == [{"name": "rack-01"}]
    assert result.source == "stdin"
    assert result.file_path is None


def test_stdin_json_sniffed() -> None:
    stdin = io.StringIO('{"name": "rack-01"}')
    result = collect(file=Path("-"), fields=[], stdin=stdin)
    assert result.records == [{"name": "rack-01"}]
    assert result.source == "stdin"


def test_field_only_no_file() -> None:
    result = collect(file=None, fields=["name=rack-01", "status=active"], stdin=None)
    assert result.records == [{"name": "rack-01", "status": "active"}]
    assert result.source == "fields_only"
    assert result.file_path is None


def test_field_overrides_file_value(tmp_path: Path) -> None:
    p = tmp_path / "device.yaml"
    p.write_text("name: original\nstatus: active\n", encoding="utf-8")
    result = collect(file=p, fields=["name=overridden"], stdin=None)
    assert result.records == [{"name": "overridden", "status": "active"}]
    assert result.source == "file_plus_fields"


def test_field_dotted_path_writes_nested(tmp_path: Path) -> None:
    result = collect(file=None, fields=["site.name=us-east-1", "site.region=us"], stdin=None)
    assert result.records == [{"site": {"name": "us-east-1", "region": "us"}}]


def test_field_indexed_list_rejected() -> None:
    with pytest.raises(InputError) as exc_info:
        collect(file=None, fields=["tags[0].name=x"], stdin=None)
    assert "use -f for nested lists" in str(exc_info.value).lower()


def test_field_without_equals_rejected() -> None:
    with pytest.raises(InputError):
        collect(file=None, fields=["bare-flag"], stdin=None)


def test_no_input_at_all_rejected() -> None:
    with pytest.raises(InputError) as exc_info:
        collect(file=None, fields=[], stdin=None)
    assert "no input" in str(exc_info.value).lower()


def test_file_does_not_exist(tmp_path: Path) -> None:
    with pytest.raises(InputError) as exc_info:
        collect(file=tmp_path / "missing.yaml", fields=[], stdin=None)
    assert "does not exist" in str(exc_info.value).lower()


def test_file_extension_unsupported(tmp_path: Path) -> None:
    p = tmp_path / "device.txt"
    p.write_text("name: x", encoding="utf-8")
    with pytest.raises(InputError) as exc_info:
        collect(file=p, fields=[], stdin=None)
    assert ".yaml" in str(exc_info.value).lower() or "extension" in str(exc_info.value).lower()


def test_file_too_large_rejected(tmp_path: Path) -> None:
    p = tmp_path / "huge.json"
    # 11 MB > 10 MB cap
    p.write_bytes(b'{"name": "' + b"x" * (11 * 1024 * 1024) + b'"}')
    with pytest.raises(InputError) as exc_info:
        collect(file=p, fields=[], stdin=None)
    assert "10" in str(exc_info.value)


def test_file_with_bom_stripped(tmp_path: Path) -> None:
    p = tmp_path / "device.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"name": "x"}).encode("utf-8"))
    result = collect(file=p, fields=[], stdin=None)
    assert result.records == [{"name": "x"}]


def test_file_non_utf8_rejected(tmp_path: Path) -> None:
    p = tmp_path / "device.json"
    p.write_bytes(b"\xff\xfe\x00\x00garbage")
    with pytest.raises(InputError) as exc_info:
        collect(file=p, fields=[], stdin=None)
    assert "utf-8" in str(exc_info.value).lower() or "encoding" in str(exc_info.value).lower()


def test_file_top_level_list_returns_list_with_explicit_flag(tmp_path: Path) -> None:
    # 3b *parses* lists but downstream registration rejects them with a 3c-pending
    # message. The parsing layer surfaces the shape via is_explicit_list.
    p = tmp_path / "devices.yaml"
    p.write_text("- name: a\n- name: b\n", encoding="utf-8")
    result = collect(file=p, fields=[], stdin=None)
    assert result.records == [{"name": "a"}, {"name": "b"}]
    assert result.is_explicit_list is True


def test_file_empty_list_rejected(tmp_path: Path) -> None:
    p = tmp_path / "empty.yaml"
    p.write_text("[]\n", encoding="utf-8")
    with pytest.raises(InputError) as exc_info:
        collect(file=p, fields=[], stdin=None)
    assert "empty" in str(exc_info.value).lower()


def test_file_top_level_scalar_rejected(tmp_path: Path) -> None:
    p = tmp_path / "scalar.yaml"
    p.write_text("just-a-string\n", encoding="utf-8")
    with pytest.raises(InputError):
        collect(file=p, fields=[], stdin=None)


def test_file_plus_fields_applies_to_every_record(tmp_path: Path) -> None:
    p = tmp_path / "devices.yaml"
    p.write_text("- name: a\n- name: b\n", encoding="utf-8")
    result = collect(file=p, fields=["status=active"], stdin=None)
    assert result.records == [
        {"name": "a", "status": "active"},
        {"name": "b", "status": "active"},
    ]
    assert result.is_explicit_list is True
