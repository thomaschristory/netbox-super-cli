"""Stage 1 of the write pipeline: collect raw input.

Reads `-f file` (yaml/yml/json), `-f -` (stdin sniffed), and `--field k=v`
flag values; merges them into a single `RawWriteInput`.

Spec §4.7.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, TextIO

import yaml
from pydantic import BaseModel, ConfigDict, Field

_FILE_SIZE_CAP_BYTES = 10 * 1024 * 1024
_SUPPORTED_EXTENSIONS = frozenset({".yaml", ".yml", ".json"})
_BOM = "﻿"


class InputError(ValueError):
    """A user-facing error during input collection. Maps to ErrorType.CLIENT."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RawWriteInput(_Frozen):
    records: list[dict[str, Any]] = Field(default_factory=list)
    source: Literal["file", "stdin", "fields_only", "file_plus_fields"]
    file_path: Path | None = None
    is_explicit_list: bool = False


def collect(
    *,
    file: Path | None,
    fields: list[str],
    stdin: TextIO | None,
) -> RawWriteInput:
    """Read a file or stdin and merge --field overrides.

    Args:
        file: A `Path` to a yaml/yml/json file, or `Path("-")` for stdin, or None.
        fields: A list of `key=value` strings (key may be a dotted path).
        stdin: A text stream to read from when `file == Path("-")`.
    """
    if file is None and not fields and stdin is None:
        raise InputError("no input: pass -f FILE, --field k=v, or pipe to stdin")

    file_records: list[dict[str, Any]] = []
    is_list = False
    file_path: Path | None = None
    used_file = False
    used_stdin = False
    if file is not None and str(file) == "-":
        if stdin is None:
            raise InputError("`-f -` requires stdin to be readable")
        file_records, is_list = _parse_stdin(stdin)
        used_stdin = True
    elif file is not None:
        file_records, is_list = _parse_file(file)
        file_path = file
        used_file = True

    field_overlay = _parse_fields(fields)

    records = _merge(file_records, field_overlay, used_file=used_file)
    source: Literal["file", "stdin", "fields_only", "file_plus_fields"]
    if used_stdin:
        source = "stdin"
    elif used_file and field_overlay:
        source = "file_plus_fields"
    elif used_file:
        source = "file"
    else:
        source = "fields_only"
    return RawWriteInput(
        records=records,
        source=source,
        file_path=file_path,
        is_explicit_list=is_list,
    )


def _parse_file(path: Path) -> tuple[list[dict[str, Any]], bool]:
    if not path.exists():
        raise InputError(f"input file does not exist: {path}")
    if path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
        raise InputError(
            f"unsupported file extension {path.suffix!r}; "
            f"expected one of: {sorted(_SUPPORTED_EXTENSIONS)}"
        )
    if path.stat().st_size > _FILE_SIZE_CAP_BYTES:
        raise InputError(f"input file exceeds 10 MB cap: {path}")
    raw = path.read_bytes()
    text = _decode_utf8(raw, path)
    return _parse_text(text, hint=path.suffix.lower())


def _parse_stdin(stream: TextIO) -> tuple[list[dict[str, Any]], bool]:
    text = stream.read()
    return _parse_text(text, hint=None)


def _decode_utf8(raw: bytes, path: Path) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError(f"input file is not valid UTF-8: {path}: {exc}") from exc
    if text.startswith(_BOM):
        text = text[len(_BOM) :]
    return text


def _parse_text(text: str, *, hint: str | None) -> tuple[list[dict[str, Any]], bool]:
    stripped = text.lstrip()
    if hint == ".json":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InputError(f"could not parse JSON input: {exc}") from exc
    elif hint is None and stripped.startswith(("{", "[")):
        # Sniffed JSON-shape on stdin; try strict JSON first, fall back to YAML
        # so flow-style YAML (e.g. `{name: foo}`) still parses.
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            try:
                parsed = yaml.safe_load(text)
            except yaml.YAMLError as exc:
                raise InputError(f"could not parse stdin as JSON or YAML: {exc}") from exc
    else:
        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise InputError(f"could not parse YAML input: {exc}") from exc
    return _normalize_top_level(parsed)


def _normalize_top_level(parsed: Any) -> tuple[list[dict[str, Any]], bool]:
    if isinstance(parsed, dict):
        return [parsed], False
    if isinstance(parsed, list):
        if not parsed:
            raise InputError("input file contains an empty list; nothing to apply")
        for i, item in enumerate(parsed):
            if not isinstance(item, dict):
                raise InputError(
                    f"input file list item {i} is not a mapping (got {type(item).__name__})"
                )
        return list(parsed), True
    raise InputError(
        f"input top-level must be a mapping or list of mappings, got {type(parsed).__name__}"
    )


def _parse_fields(raw: list[str]) -> dict[str, Any]:
    overlay: dict[str, Any] = {}
    for item in raw:
        if "=" not in item:
            raise InputError(f"--field expects key=value, got: {item!r}")
        key, _, value = item.partition("=")
        key = key.strip()
        if not key:
            raise InputError(f"--field key is empty: {item!r}")
        if "[" in key or "]" in key:
            raise InputError(
                f"--field {item!r} uses indexed-list syntax; use -f for nested lists in 3b"
            )
        _set_dotted(overlay, key.split("."), value)
    return overlay


def _set_dotted(target: dict[str, Any], parts: list[str], value: str) -> None:
    cursor = target
    for part in parts[:-1]:
        existing = cursor.get(part)
        if not isinstance(existing, dict):
            existing = {}
            cursor[part] = existing
        cursor = existing
    cursor[parts[-1]] = value


def _merge(
    file_records: list[dict[str, Any]],
    overlay: dict[str, Any],
    *,
    used_file: bool,
) -> list[dict[str, Any]]:
    if not used_file and not file_records:
        return [_deep_copy(overlay)]
    out: list[dict[str, Any]] = []
    for record in file_records:
        merged = _deep_merge(_deep_copy(record), overlay)
        out.append(merged)
    return out


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value


def _deep_merge(target: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Mutating deep merge. Overlay wins on leaves."""
    for k, v in overlay.items():
        existing = target.get(k)
        if isinstance(existing, dict) and isinstance(v, dict):
            _deep_merge(existing, v)
        else:
            target[k] = _deep_copy(v)
    return target


__all__ = ["InputError", "RawWriteInput", "collect"]
