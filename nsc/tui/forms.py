"""Pure, framework-free mapping from a `FieldShape` to a widget spec.

No Textual import: this is the unit-testable core that the edit screens consume
to decide which concrete widget to render for each field.
"""

from __future__ import annotations

import enum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from nsc.model.command_model import FieldShape, PrimitiveType

WidgetKind = Literal["select", "switch", "number", "text", "masked"]


class _SetNull(enum.Enum):
    """Staging sentinel: distinguishes an explicit null from an untouched field."""

    TOKEN = "SET_NULL"


SET_NULL = _SetNull.TOKEN


class WidgetSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: WidgetKind
    name: str
    choices: tuple[str, ...] = ()
    nullable: bool = False
    sensitive: bool = False
    is_float: bool = False


def field_to_widget(name: str, field: FieldShape, sensitive_paths: tuple[str, ...]) -> WidgetSpec:
    sensitive = name in sensitive_paths
    if sensitive:
        return WidgetSpec(kind="masked", name=name, nullable=field.nullable, sensitive=True)
    if field.enum is not None:
        return WidgetSpec(
            kind="select", name=name, choices=tuple(field.enum), nullable=field.nullable
        )
    if field.primitive is PrimitiveType.BOOLEAN:
        return WidgetSpec(kind="switch", name=name, nullable=field.nullable)
    if field.primitive in (PrimitiveType.INTEGER, PrimitiveType.NUMBER):
        return WidgetSpec(
            kind="number",
            name=name,
            nullable=field.nullable,
            is_float=field.primitive is PrimitiveType.NUMBER,
        )
    return WidgetSpec(kind="text", name=name, nullable=field.nullable)


class DiffRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    old_display: str
    new_display: str


def _staged_differs(original_value: object, staged_value: object) -> bool:
    if staged_value is SET_NULL:
        return original_value is not None
    if isinstance(original_value, dict) and isinstance(staged_value, int):
        return original_value.get("id") != staged_value
    return original_value != staged_value


def compute_patch(original: dict[str, object], staged: dict[str, object]) -> dict[str, object]:
    """Return only the fields whose staged value differs from the original.

    FK fields whose original is a nested dict are compared by ``id`` against the
    staged integer. ``SET_NULL`` emits ``None`` unless the field was already null.
    """
    patch: dict[str, object] = {}
    for name, staged_value in staged.items():
        original_value = original.get(name)
        if not _staged_differs(original_value, staged_value):
            continue
        patch[name] = None if staged_value is SET_NULL else staged_value
    return patch


def _display(value: object) -> str:
    if isinstance(value, dict):
        ident = value.get("id")
        if ident is not None:
            return str(ident)
    return str(value)


def diff_rows(
    original: dict[str, object],
    patch: dict[str, object],
    sensitive_paths: tuple[str, ...],
) -> list[DiffRow]:
    """Render ``patch`` as human-readable old -> new rows for the confirm modal."""
    rows: list[DiffRow] = []
    for name, new_value in patch.items():
        if name in sensitive_paths:
            rows.append(DiffRow(field=name, old_display="****", new_display="****"))
            continue
        old_display = _display(original[name]) if name in original else ""
        rows.append(DiffRow(field=name, old_display=old_display, new_display=str(new_value)))
    return rows
