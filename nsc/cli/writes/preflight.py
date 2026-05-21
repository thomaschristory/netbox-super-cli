"""Stage 2 of the write pipeline: best-effort preflight validation.

Three checks per record (spec §4.6):
  1. required fields present (top-level only),
  2. primitive type matches,
  3. enum value is in the allowed set.

Explicitly NOT validated: oneOf/anyOf/allOf, pattern/format/minLength/maxLength,
foreign-key existence, cross-field rules. NetBox is the source of truth for
those — server-side 400s surface as ErrorType.VALIDATION with source="server".
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from nsc.cli.writes.coercion import BOOL_STRINGS as _BOOL_STRINGS
from nsc.cli.writes.input import RawWriteInput
from nsc.model.command_model import (
    FieldShape,
    Operation,
    PrimitiveType,
    RequestBodyShape,
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Issue(_Frozen):
    record_index: int
    field_path: str
    kind: Literal["missing_required", "type_mismatch", "enum_invalid"]
    message: str
    expected: str | None = None


class PreflightResult(_Frozen):
    ok: bool
    issues: list[Issue] = Field(default_factory=list)


def check(raw: RawWriteInput, operation: Operation) -> PreflightResult:
    body = operation.request_body
    if body is None:
        return PreflightResult(ok=True)
    issues: list[Issue] = []
    for index, record in enumerate(raw.records):
        issues.extend(_check_required(index, record, body))
        issues.extend(_check_fields(index, record, body))
    return PreflightResult(ok=not issues, issues=issues)


def _check_required(index: int, record: dict[str, Any], body: RequestBodyShape) -> list[Issue]:
    return [
        Issue(
            record_index=index,
            field_path=name,
            kind="missing_required",
            message=f"required field {name!r} is missing",
        )
        for name in body.required
        if name not in record
    ]


def _check_fields(index: int, record: dict[str, Any], body: RequestBodyShape) -> list[Issue]:
    out: list[Issue] = []
    for name, value in record.items():
        shape = body.fields.get(name)
        if shape is None:
            continue
        type_issue = _check_primitive(index, name, value, shape)
        if type_issue is not None:
            out.append(type_issue)
            continue
        enum_issue = _check_enum(index, name, value, shape)
        if enum_issue is not None:
            out.append(enum_issue)
    return out


def _check_primitive(index: int, name: str, value: Any, shape: FieldShape) -> Issue | None:
    if value is None and shape.nullable:
        return None
    if _value_matches_primitive(value, shape.primitive):
        return None
    return Issue(
        record_index=index,
        field_path=name,
        kind="type_mismatch",
        message=(f"field {name!r} expected {shape.primitive.value}, got {type(value).__name__}"),
        expected=shape.primitive.value,
    )


def _matches_string(value: Any) -> bool:
    return isinstance(value, str)


def _matches_integer(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, str) and _is_int_string(value)


def _matches_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return isinstance(value, str) and _is_float_string(value)


def _matches_boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    return isinstance(value, str) and value.strip().lower() in _BOOL_STRINGS


def _matches_array(value: Any) -> bool:
    return isinstance(value, list)


def _matches_object(value: Any) -> bool:
    return isinstance(value, dict)


_PRIMITIVE_MATCHERS: dict[PrimitiveType, Callable[[Any], bool]] = {
    PrimitiveType.STRING: _matches_string,
    PrimitiveType.INTEGER: _matches_integer,
    PrimitiveType.NUMBER: _matches_number,
    PrimitiveType.BOOLEAN: _matches_boolean,
    PrimitiveType.ARRAY: _matches_array,
    PrimitiveType.OBJECT: _matches_object,
}


def _value_matches_primitive(value: Any, primitive: PrimitiveType) -> bool:
    matcher = _PRIMITIVE_MATCHERS.get(primitive)
    if matcher is None:
        return True  # UNKNOWN — let the server arbitrate
    return matcher(value)


def _is_int_string(value: str) -> bool:
    s = value.strip()
    if s.startswith(("-", "+")):
        s = s[1:]
    return s.isdigit()


def _is_float_string(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _check_enum(index: int, name: str, value: Any, shape: FieldShape) -> Issue | None:
    if not shape.enum:
        return None
    if str(value) in shape.enum:
        return None
    return Issue(
        record_index=index,
        field_path=name,
        kind="enum_invalid",
        message=f"field {name!r}={value!r} not in allowed set",
        expected=", ".join(shape.enum),
    )


__all__ = ["Issue", "PreflightResult", "check"]
