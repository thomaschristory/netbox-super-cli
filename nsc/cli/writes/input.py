"""Stage 1 of the write pipeline: collect raw input.

Reads `-f file` (yaml/yml/json), `-f -` (stdin sniffed), and `--field k=v`
flag values; merges them into a single `RawWriteInput`.

Spec §4.7.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Literal, TextIO

from pydantic import BaseModel, ConfigDict, Field
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

_FILE_SIZE_CAP_BYTES = 10 * 1024 * 1024
_SUPPORTED_EXTENSIONS = frozenset({".yaml", ".yml", ".json", ".ndjson", ".jsonl"})
_NDJSON_BAD_LINE_CAP = 20
_BOM = "﻿"
_STDIN_SNIFF_BYTES = 512


def _safe_load(text: str) -> Any:
    """Parse a YAML/JSON document with ruamel's safe loader.

    Returns plain Python primitives (`dict` / `list` / scalar), not the
    round-trip CommentedMap/CommentedSeq — downstream `_normalize_top_level`
    expects `dict` / `list`.
    """
    return YAML(typ="safe", pure=True).load(io.StringIO(text))


class InputError(ValueError):
    """A user-facing error during input collection. Maps to ErrorType.CLIENT."""


class NDJSONParseError(InputError):
    """One or more NDJSON lines failed to parse. Carries a bounded `bad_lines` list."""

    def __init__(self, bad_lines: list[dict[str, Any]], *, total_lines: int) -> None:
        self.bad_lines = bad_lines
        self.total_lines = total_lines
        message = (
            f"{len(bad_lines)} of {total_lines} NDJSON line(s) failed to parse; "
            f"see details.bad_lines"
        )
        super().__init__(message)


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
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise InputError(f"could not read input file {path}: {exc}") from exc
    text = _decode_utf8(raw, path)
    suffix = path.suffix.lower()
    if suffix in {".ndjson", ".jsonl"}:
        return _parse_ndjson(text), True
    return _parse_text(text, hint=suffix)


def _parse_ndjson(text: str) -> list[dict[str, Any]]:
    """Parse one JSON object per non-blank line.

    All-or-nothing semantics: if ANY line fails, raise `NDJSONParseError` with
    a `bad_lines` list capped at `_NDJSON_BAD_LINE_CAP` entries. Blank/whitespace
    lines are skipped (not counted as bad). Empty input → InputError.
    """
    records: list[dict[str, Any]] = []
    bad_lines: list[dict[str, Any]] = []
    total = 0
    seen_any = False

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        seen_any = True
        total += 1
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            if len(bad_lines) < _NDJSON_BAD_LINE_CAP:
                bad_lines.append({"line": lineno, "reason": str(exc)})
            continue
        if not isinstance(parsed, dict):
            if len(bad_lines) < _NDJSON_BAD_LINE_CAP:
                bad_lines.append(
                    {
                        "line": lineno,
                        "reason": f"top-level value is not a mapping (got {type(parsed).__name__})",
                    }
                )
            continue
        records.append(parsed)

    if not seen_any:
        raise InputError("input file contains no records (NDJSON file is empty or all blank)")
    if bad_lines:
        raise NDJSONParseError(bad_lines, total_lines=total)
    return records


def _parse_stdin(stream: TextIO) -> tuple[list[dict[str, Any]], bool]:
    text = stream.read()
    if not text.strip():
        raise InputError("stdin is empty; nothing to apply")
    return _parse_text(text, hint=_sniff_stdin_format(text))


def _sniff_stdin_format(text: str) -> str | None:
    """Inspect the first ~512 chars and return a parser hint.

    Returns:
      - "ndjson"        → all-or-nothing NDJSON parser
      - "json_or_yaml"  → strict JSON first, YAML fallback (preserves flow-YAML)
      - None            → YAML (which also accepts JSON)
    """
    prefix = text[:_STDIN_SNIFF_BYTES]
    stripped = prefix.lstrip()
    if not stripped:
        return None
    first = stripped[0]
    if first == "[":
        return "json_or_yaml"
    if first != "{":
        return None
    return _classify_brace_start(stripped)


def _classify_brace_start(stripped: str) -> str:
    """Walk the first JSON object in `stripped` to decide single vs NDJSON.

    If the first complete object is followed by any non-whitespace content,
    we treat the input as NDJSON (even if the next "line" is not valid JSON —
    the NDJSON parser will collect those as bad_lines and raise NDJSONParseError).
    """
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(stripped):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                rest = stripped[i + 1 :]
                if rest.strip():
                    # Any non-whitespace after the first object → NDJSON.
                    return "ndjson"
                # Nothing follows → single object.
                return "json_or_yaml"
    # Buffer ended mid-object; default to JSON-or-YAML.
    return "json_or_yaml"


def _decode_utf8(raw: bytes, path: Path) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError(f"input file is not valid UTF-8: {path}: {exc}") from exc
    if text.startswith(_BOM):
        text = text[len(_BOM) :]
    return text


def _parse_text(text: str, *, hint: str | None) -> tuple[list[dict[str, Any]], bool]:
    if hint == "ndjson":
        return _parse_ndjson(text), True
    if hint == ".json":
        # File-extension was .json; require strict JSON, no YAML fallback.
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InputError(f"could not parse JSON input: {exc}") from exc
    elif hint == "json_or_yaml" or (hint is None and text.lstrip().startswith(("{", "["))):
        # Stdin sniffer hint OR legacy fallback: try JSON first, then YAML.
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            try:
                parsed = _safe_load(text)
            except YAMLError as exc:
                raise InputError(f"could not parse stdin as JSON or YAML: {exc}") from exc
    else:
        try:
            parsed = _safe_load(text)
        except YAMLError as exc:
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


__all__ = ["InputError", "NDJSONParseError", "RawWriteInput", "collect"]
