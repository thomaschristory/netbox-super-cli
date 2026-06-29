"""Pure, framework-free mapping from a `FieldShape` to a widget spec.

No Textual import: this is the unit-testable core that the edit screens consume
to decide which concrete widget to render for each field.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from nsc.model.command_model import FieldShape, PrimitiveType
from nsc.savedfilters.custom_fields import CustomFieldDef
from nsc.savedfilters.tags import TagDef

WidgetKind = Literal["select", "switch", "number", "text", "masked", "multi_select"]

_CF_PREFIX = "custom_fields."


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
    # multi_select only: (label, value) options and the currently-selected values.
    options: tuple[tuple[str, str], ...] = ()
    selected: tuple[str, ...] = ()


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


_CF_KINDS: dict[str, WidgetKind] = {
    "integer": "number",
    "decimal": "number",
    "boolean": "switch",
    "select": "select",
    "multiselect": "multi_select",
}


def custom_field_widget(cf: CustomFieldDef) -> WidgetSpec:
    """Widget spec for one custom field, keyed by its ``custom_fields.<name>`` path.

    The type drives the widget; ``select``/``multiselect`` carry the choice set.
    Unknown/object types fall back to a text input.
    """
    name = f"{_CF_PREFIX}{cf.name}"
    kind = _CF_KINDS.get(cf.type, "text")
    nullable = not cf.required
    if kind == "select":
        return WidgetSpec(kind="select", name=name, choices=cf.choices, nullable=nullable)
    if kind == "multi_select":
        return WidgetSpec(
            kind="multi_select",
            name=name,
            options=tuple((c, c) for c in cf.choices),
            nullable=nullable,
        )
    return WidgetSpec(kind=kind, name=name, nullable=nullable, is_float=cf.type == "decimal")


def expand_custom_fields(defs: dict[str, CustomFieldDef]) -> list[WidgetSpec]:
    """One widget spec per custom field, in definition order."""
    return [custom_field_widget(cf) for cf in defs.values()]


def encode_field_id(name: str) -> str:
    """Make a field name safe for a Textual widget id (dots are invalid there).

    NetBox field and custom-field names are ``[a-z0-9_]+``, so the only dot is the
    ``custom_fields.<name>`` separator; ``.`` -> ``-`` round-trips losslessly.
    """
    return name.replace(".", "-")


def decode_field_id(token: str) -> str:
    """Inverse of :func:`encode_field_id` (applied after stripping the id prefix)."""
    return token.replace("-", ".")


def tag_slugs(value: object) -> tuple[str, ...]:
    """Slugs of a record's ``tags`` list (falling back to name), or empty."""
    if not isinstance(value, list):
        return ()
    slugs: list[str] = []
    for item in value:
        if isinstance(item, dict):
            slug = item.get("slug") or item.get("name")
            if slug:
                slugs.append(str(slug))
    return tuple(slugs)


def tags_widget_spec(
    name: str, tags: tuple[TagDef, ...], current_slugs: tuple[str, ...]
) -> WidgetSpec:
    """Multi-select spec offering every tag (label/slug) with current ones selected."""
    return WidgetSpec(
        kind="multi_select",
        name=name,
        options=tuple((t.label, t.slug) for t in tags),
        selected=current_slugs,
        nullable=True,
    )


def tags_payload(slugs: Iterable[str], tags: tuple[TagDef, ...]) -> list[dict[str, str]]:
    """Build a NetBox writable ``tags`` payload (list of ``{name, slug}``).

    Unknown slugs (a tag list that couldn't be resolved) fall back to using the
    slug as both name and slug so the payload is still well-formed.
    """
    by_slug = {t.slug: t for t in tags}
    payload: list[dict[str, str]] = []
    for slug in slugs:
        tag = by_slug.get(slug)
        if tag is not None:
            payload.append({"name": tag.name, "slug": tag.slug})
        else:
            payload.append({"name": slug, "slug": slug})
    return payload


def flatten_custom_fields(record: dict[str, Any]) -> dict[str, Any]:
    """Copy of ``record`` with ``custom_fields`` exploded into dotted keys.

    Lets :func:`compute_patch` diff each custom field individually against the
    widget-staged ``custom_fields.<name>`` values. The original is not mutated.
    """
    flat = dict(record)
    cf = record.get("custom_fields")
    if isinstance(cf, dict):
        for key, value in cf.items():
            flat[f"{_CF_PREFIX}{key}"] = value
    return flat


def nest_custom_fields(patch: dict[str, Any]) -> dict[str, Any]:
    """Fold ``custom_fields.<name>`` patch entries back into one nested dict.

    NetBox expects custom fields nested under ``custom_fields``; the widgets stage
    them flat. Non-custom-field entries pass through unchanged.
    """
    nested: dict[str, Any] = {}
    result: dict[str, Any] = {}
    for key, value in patch.items():
        if key.startswith(_CF_PREFIX):
            nested[key[len(_CF_PREFIX) :]] = value
        else:
            result[key] = value
    if nested:
        result["custom_fields"] = nested
    return result


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


def fk_display(value: object) -> str:
    """Human-readable label for a value, resolving FK nested objects.

    NetBox FK objects carry ``display`` (and usually ``name``/``slug``); prefer
    those over the bare ``id`` so the diff shows e.g. ``Top of Rack Switch``
    rather than ``12``. Non-dict values render via ``str``.
    """
    if isinstance(value, dict):
        for key in ("display", "name", "slug"):
            label = value.get(key)
            if label:
                return str(label)
        ident = value.get("id")
        if ident is not None:
            return str(ident)
    return str(value)


def diff_rows(
    original: dict[str, object],
    patch: dict[str, object],
    sensitive_paths: tuple[str, ...],
    new_displays: dict[str, str] | None = None,
) -> list[DiffRow]:
    """Render ``patch`` as human-readable old -> new rows for the confirm modal.

    ``new_displays`` overrides a field's rendered *new* value — used for FK
    fields whose staged value is a bare id but whose chosen label is known
    (e.g. picked from the record chooser). The patch still carries the id.
    """
    overrides = new_displays or {}
    rows: list[DiffRow] = []
    for name, new_value in patch.items():
        if name in sensitive_paths:
            rows.append(DiffRow(field=name, old_display="****", new_display="****"))
            continue
        old_display = fk_display(original[name]) if name in original else ""
        new_display = overrides.get(name, str(new_value))
        rows.append(DiffRow(field=name, old_display=old_display, new_display=new_display))
    return rows
