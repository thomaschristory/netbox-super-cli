"""Resolve a model's custom-field definitions (name -> label, type, choices).

The list payload's ``custom_fields`` dict is keyed by field *name* only; the
human label and type live in the definitions at ``/api/extras/custom-fields/``,
filtered by ``object_type`` (e.g. ``dcim.device``). This mirrors
:class:`~nsc.savedfilters.objecttypes.ObjectTypeResolver`: fetch once per object
type, cache, and return ``None`` (never raise) when the registry can't be reached
so callers fall back to the raw key. Used to show custom-field column labels
(#132) and to build per-field edit widgets (#134).

Choice values for ``select``/``multiselect`` fields come from a referenced
choice set; they are fetched best-effort and left empty on any failure.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from nsc.http.errors import NetBoxAPIError, NetBoxClientError
from nsc.savedfilters.objecttypes import ObjectTypeResolver

_CUSTOM_FIELDS_PATH = "/api/extras/custom-fields/"
_CHOICE_SETS_PATH = "/api/extras/custom-field-choice-sets/"
_CF_PREFIX = "custom_fields."


class _ClientLike(Protocol):
    def paginate(
        self, path: str, params: dict[str, Any] | None = ..., *, limit: int | None = ...
    ) -> Any: ...

    def get(self, path: str, params: dict[str, Any] | None = ...) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CustomFieldDef:
    name: str
    label: str
    type: str = "text"
    choices: tuple[str, ...] = ()
    required: bool = False


def humanize(name: str) -> str:
    """``site_contact`` -> ``Site Contact`` (fallback when a label is blank)."""
    cleaned = name.replace("_", " ").strip()
    return cleaned.title() if cleaned else name


def custom_field_labels(
    columns: Iterable[str], defs: dict[str, CustomFieldDef] | None
) -> dict[str, str]:
    """Map every column key to its display label.

    Non-custom-field keys map to themselves. ``custom_fields.<name>`` keys map to
    the field's resolved label. When two visible custom-field columns resolve to
    the same label they are ambiguous, so both fall back to their raw key. Unknown
    custom fields and a missing ``defs`` also fall back to the raw key.
    """
    cols = list(columns)
    if not defs:
        return {col: col for col in cols}
    resolved: dict[str, str] = {}
    for col in cols:
        if col.startswith(_CF_PREFIX) and (cf := defs.get(col[len(_CF_PREFIX) :])) is not None:
            resolved[col] = cf.label
    seen: dict[str, list[str]] = {}
    for col, label in resolved.items():
        seen.setdefault(label, []).append(col)
    labels: dict[str, str] = {}
    for col in cols:
        unique = resolved.get(col)
        if unique is not None and len(seen[unique]) == 1:
            labels[col] = unique
        else:
            labels[col] = col
    return labels


class CustomFieldResolver:
    """Looks up custom-field definitions from the live API, cached per object type."""

    def __init__(self, client: _ClientLike, object_types: ObjectTypeResolver | None = None) -> None:
        self._client = client
        self._object_types = object_types or ObjectTypeResolver(client)
        self._cache: dict[str, dict[str, CustomFieldDef]] = {}
        self._choice_cache: dict[int, tuple[str, ...]] = {}

    def resolve(self, list_path: str) -> dict[str, CustomFieldDef] | None:
        """``{name: CustomFieldDef}`` for a list path, or ``None`` if unresolvable."""
        object_type = self._object_types.resolve(list_path)
        if object_type is None:
            return None
        if object_type in self._cache:
            return self._cache[object_type]
        try:
            records = list(self._client.paginate(_CUSTOM_FIELDS_PATH, {"object_type": object_type}))
        except (NetBoxAPIError, NetBoxClientError):
            return None
        defs = {d.name: d for d in (self._to_def(rec) for rec in records)}
        self._cache[object_type] = defs
        return defs

    def _to_def(self, record: dict[str, Any]) -> CustomFieldDef:
        name = str(record.get("name", ""))
        raw_label = record.get("label")
        label = raw_label if isinstance(raw_label, str) and raw_label else humanize(name)
        cf_type = record.get("type")
        type_value = cf_type.get("value") if isinstance(cf_type, dict) else cf_type
        type_str = type_value if isinstance(type_value, str) else "text"
        choices = self._choices_for(record.get("choice_set"))
        return CustomFieldDef(
            name=name,
            label=label,
            type=type_str,
            choices=choices,
            required=bool(record.get("required", False)),
        )

    def _choices_for(self, choice_set: Any) -> tuple[str, ...]:
        if not isinstance(choice_set, dict):
            return ()
        cs_id = choice_set.get("id")
        if not isinstance(cs_id, int):
            return ()
        if cs_id in self._choice_cache:
            return self._choice_cache[cs_id]
        try:
            payload = self._client.get(f"{_CHOICE_SETS_PATH}{cs_id}/")
        except (NetBoxAPIError, NetBoxClientError):
            return ()
        values = _extract_choice_values(payload)
        self._choice_cache[cs_id] = values
        return values


def _extract_choice_values(payload: dict[str, Any]) -> tuple[str, ...]:
    raw = payload.get("choices")
    if not isinstance(raw, list):
        raw = payload.get("extra_choices")
    if not isinstance(raw, list):
        return ()
    values: list[str] = []
    for item in raw:
        if isinstance(item, (list, tuple)) and item:
            values.append(str(item[0]))
        elif isinstance(item, str):
            values.append(item)
    return tuple(values)
