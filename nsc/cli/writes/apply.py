"""Stage 3 of the write pipeline: build the wire-shape ResolvedRequest.

3b emits one ResolvedRequest per input record. 3c will add a bulk variant
that produces a single request with a list-shaped body.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from nsc.cli.writes.bulk import RoutingMode
from nsc.cli.writes.input import RawWriteInput
from nsc.model.command_model import FieldShape, HttpMethod, Operation, PrimitiveType

_REDACTED_AUTH = "Token <redacted>"
_TRUTHY = {"true", "1", "yes"}
_FALSY = {"false", "0", "no"}


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ResolvedRequest(_Frozen):
    method: HttpMethod
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] | list[dict[str, Any]] | None = None
    path_vars: dict[str, str] = Field(default_factory=dict)
    operation_id: str
    record_indices: list[int] = Field(default_factory=list)


def resolve(
    raw: RawWriteInput,
    operation: Operation,
    *,
    path_vars: dict[str, str],
    base_url: str,
    headers: dict[str, str] | None = None,
    mode: RoutingMode = RoutingMode.SINGLE,
) -> list[ResolvedRequest]:
    """Build wire-shape requests.

    Mode drives the body shape:
      SINGLE / LOOP -> one ResolvedRequest per record, body=dict, record_indices=[i].
      BULK          -> one ResolvedRequest, body=list[dict], record_indices=[0..N).

    SINGLE and LOOP differ only in caller intent (single record vs. multiple
    records that the user opted out of bulk for). The wire shape is identical
    per request.
    """
    base = base_url.rstrip("/")
    url = base + operation.path.format(**path_vars)
    visible_headers = _redact(headers or {})
    records = raw.records or [{}]

    if mode is RoutingMode.BULK:
        body_list = [_shape_body(r, operation) or {} for r in records]
        return [
            ResolvedRequest(
                method=operation.http_method,
                url=url,
                headers=visible_headers,
                query={},
                body=body_list,
                path_vars=dict(path_vars),
                operation_id=operation.operation_id,
                record_indices=list(range(len(records))),
            )
        ]

    out: list[ResolvedRequest] = []
    for index, record in enumerate(records):
        body = _shape_body(record, operation)
        out.append(
            ResolvedRequest(
                method=operation.http_method,
                url=url,
                headers=visible_headers,
                query={},
                body=body,
                path_vars=dict(path_vars),
                operation_id=operation.operation_id,
                record_indices=[index],
            )
        )
    return out


def _shape_body(record: dict[str, Any], operation: Operation) -> dict[str, Any] | None:
    if operation.http_method is HttpMethod.DELETE:
        return None
    if operation.request_body is None:
        return record or None
    cast_record: dict[str, Any] = {}
    for key, value in record.items():
        shape = operation.request_body.fields.get(key)
        cast_record[key] = _cast(value, shape)
    return cast_record


def _cast(value: Any, shape: FieldShape | None) -> Any:
    if shape is None or value is None:
        return value
    match shape.primitive:
        case PrimitiveType.INTEGER:
            return _cast_int(value)
        case PrimitiveType.NUMBER:
            return _cast_number(value)
        case PrimitiveType.BOOLEAN:
            return _cast_bool(value)
        case _:
            return value


def _cast_int(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return value
    return value


def _cast_number(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def _cast_bool(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUTHY:
            return True
        if lowered in _FALSY:
            return False
    return value


def _redact(headers: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() == "authorization":
            out[k] = _REDACTED_AUTH
        elif k.lower() in {"cookie", "x-api-key", "proxy-authorization"}:
            out[k] = "<redacted>"
        else:
            out[k] = v
    return out


CastSource = Literal["file", "field_flag", "default", "schema_cast"]
"""Reserved for ExplainTrace consumers. Defined here so apply.py owns the type."""


__all__ = ["CastSource", "ResolvedRequest", "resolve"]
