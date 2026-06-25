"""Pure foreign-key target resolution for the edit form.

To edit an FK we must know which resource to pick from. Two generic signals,
in priority order:

1. The record's current nested value carries a NetBox ``url`` (e.g.
   ``https://nb/api/dcim/sites/3/``); its path names the target resource and
   the trailing segment is the current id.
2. No current value (create, or null FK): resolve by field name, stripping a
   ``_id`` suffix and matching the singularized resource names.

When neither resolves, fall back to raw-ID entry with a hint — editing never
hard-blocks on an unclassifiable schema shape.
"""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

from nsc.model.command_model import CommandModel, Operation
from nsc.tui.relations import singularize

FkKind = Literal["picker", "raw_id"]

_MIN_URL_SEGMENTS = 2


def is_fk_value(value: Any) -> bool:
    """True when ``value`` is a NetBox FK nested object (carries ``id``/``url``).

    The writable schema types FK fields as ``oneOf[integer, brief-ref]`` with no
    top-level ``type``, so the model has no FK signal; the reliable runtime cue
    is the record's nested object. A bare ``custom_fields`` dict (no id/url) is
    deliberately excluded.
    """
    return isinstance(value, dict) and ("id" in value or "url" in value)


class FkTarget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: FkKind
    field_name: str
    tag: str | None = None
    resource_name: str | None = None
    list_op: Operation | None = None
    current_id: int | None = None
    hint: str | None = None


def resolve_fk_target(field_name: str, current_value: Any, model: CommandModel) -> FkTarget:
    from_url = _resolve_from_url(field_name, current_value, model)
    if from_url is not None:
        return from_url

    by_name = _resolve_by_field_name(field_name, model)
    if by_name is not None:
        return by_name

    return FkTarget(
        kind="raw_id",
        field_name=field_name,
        hint=f"Could not resolve a target resource for '{field_name}'; enter the numeric ID.",
    )


def _resolve_from_url(field_name: str, current_value: Any, model: CommandModel) -> FkTarget | None:
    if not isinstance(current_value, dict):
        return None
    url = current_value.get("url")
    if not isinstance(url, str) or not url:
        return None

    segments = [segment for segment in urlsplit(url).path.split("/") if segment]
    if len(segments) < _MIN_URL_SEGMENTS:
        return None

    resource_name = segments[-2]
    current_id = _coerce_id(segments[-1])
    located = _locate_resource(resource_name, model)
    if located is None:
        return FkTarget(
            kind="raw_id",
            field_name=field_name,
            current_id=current_id,
            hint=(f"Unknown target resource '{resource_name}' from {url}; enter the numeric ID."),
        )

    tag, list_op = located
    # A `picker` target must carry a usable list endpoint — otherwise the screen
    # renders a chooser button that can't open anything. Resolvable but
    # list-less resources fall back to raw-ID entry, like an unknown resource.
    if list_op is None:
        return FkTarget(
            kind="raw_id",
            field_name=field_name,
            current_id=current_id,
            hint=(f"'{resource_name}' has no list endpoint; enter the numeric ID."),
        )
    return FkTarget(
        kind="picker",
        field_name=field_name,
        tag=tag,
        resource_name=resource_name,
        list_op=list_op,
        current_id=current_id,
    )


def _resolve_by_field_name(field_name: str, model: CommandModel) -> FkTarget | None:
    base = field_name[:-3] if field_name.endswith("_id") else field_name
    wanted = singularize(base)
    for tag_name in sorted(model.tags):
        tag = model.tags[tag_name]
        for resource_name in sorted(tag.resources):
            if singularize(resource_name) != wanted:
                continue
            resource = tag.resources[resource_name]
            if resource.list_op is None:
                continue
            return FkTarget(
                kind="picker",
                field_name=field_name,
                tag=tag_name,
                resource_name=resource_name,
                list_op=resource.list_op,
            )
    return None


def _locate_resource(
    resource_name: str, model: CommandModel
) -> tuple[str, Operation | None] | None:
    for tag_name in sorted(model.tags):
        tag = model.tags[tag_name]
        resource = tag.resources.get(resource_name)
        if resource is not None:
            return (tag_name, resource.list_op)
    return None


def _coerce_id(segment: str) -> int | None:
    try:
        return int(segment)
    except ValueError:
        return None
