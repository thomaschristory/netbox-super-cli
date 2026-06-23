"""Pure, framework-free mapping from a `FieldShape` to a widget spec.

No Textual import: this is the unit-testable core that the edit screens consume
to decide which concrete widget to render for each field.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from nsc.model.command_model import FieldShape, PrimitiveType

WidgetKind = Literal["select", "switch", "number", "text", "masked"]


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
