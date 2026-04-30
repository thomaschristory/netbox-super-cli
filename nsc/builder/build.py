"""Schema → CommandModel.

The algorithm is deterministic and depends solely on the OpenAPI document.
No NetBox-specific knowledge is hard-coded.
"""

from __future__ import annotations

import re

from nsc.model.command_model import (
    CommandModel,
    HttpMethod,
    Operation,
    Parameter,
    ParameterLocation,
    PrimitiveType,
    Resource,
    Tag,
)
from nsc.schema.loader import LoadedSchema
from nsc.schema.models import OpenAPIDocument, PathItem, SchemaObject
from nsc.schema.models import Operation as SchemaOperation
from nsc.schema.models import Parameter as SchemaParameter

_PARAM_SEGMENT = re.compile(r"^\{[^}]+\}$")
_OP_TRAILING_VERB = re.compile(r"_(list|create|update|partial_update|destroy|retrieve|read)$")
_HTTP_METHODS: tuple[tuple[str, HttpMethod], ...] = (
    ("get", HttpMethod.GET),
    ("post", HttpMethod.POST),
    ("patch", HttpMethod.PATCH),
    ("put", HttpMethod.PUT),
    ("delete", HttpMethod.DELETE),
    ("options", HttpMethod.OPTIONS),
    ("head", HttpMethod.HEAD),
)
# api / <tag> / <resource> = at least 3 non-empty path parts
_MIN_PATH_PARTS = 3


def build_command_model(loaded: LoadedSchema) -> CommandModel:
    doc = loaded.document
    tags: dict[str, _MutableTag] = {}

    for path, item in doc.paths.items():
        for attr_name, http_method in _HTTP_METHODS:
            schema_op: SchemaOperation | None = getattr(item, attr_name)
            if schema_op is None:
                continue
            _assimilate(tags, path, http_method, schema_op, item, doc)

    final_tags = {
        name: Tag(
            name=name,
            description=mt.description,
            resources={rname: _finalize_resource(rname, mr) for rname, mr in mt.resources.items()},
        )
        for name, mt in sorted(tags.items())
    }

    return CommandModel(
        info_title=doc.info.title,
        info_version=doc.info.version,
        schema_hash=loaded.hash,
        tags=final_tags,
    )


# --- internals -------------------------------------------------------------


class _MutableResource:
    def __init__(self, name: str) -> None:
        self.name = name
        self.list_op: Operation | None = None
        self.get_op: Operation | None = None
        self.create_op: Operation | None = None
        self.update_op: Operation | None = None
        self.replace_op: Operation | None = None
        self.delete_op: Operation | None = None
        self.custom_actions: list[Operation] = []


class _MutableTag:
    def __init__(self, name: str, description: str | None) -> None:
        self.name = name
        self.description = description
        self.resources: dict[str, _MutableResource] = {}


def _assimilate(
    tags: dict[str, _MutableTag],
    path: str,
    http_method: HttpMethod,
    schema_op: SchemaOperation,
    item: PathItem,
    doc: OpenAPIDocument,
) -> None:
    tag_name = schema_op.tags[0] if schema_op.tags else None
    if tag_name is None:
        return  # untagged operations are skipped intentionally

    resource_name, is_collection_path = _resource_from_path(path, tag_name)
    if resource_name is None:
        return  # paths that don't match the /api/<tag>/<resource>/... shape

    tag = tags.get(tag_name)
    if tag is None:
        tag = _MutableTag(tag_name, _tag_description(tag_name, doc))
        tags[tag_name] = tag

    resource = tag.resources.get(resource_name)
    if resource is None:
        resource = _MutableResource(resource_name)
        tag.resources[resource_name] = resource

    op = _to_model_operation(path, http_method, schema_op, item)
    classification = _classify(http_method, path, schema_op, resource_name)
    _attach(resource, classification, op, is_collection_path)


def _resource_from_path(path: str, tag: str) -> tuple[str | None, bool]:
    """Return (resource_name, is_collection_path).

    A path is a collection path if it has no further parameter segments after
    the resource name. `is_collection_path=True` for `/api/dcim/devices/`
    and `False` for `/api/dcim/devices/{id}/`.
    """
    parts = [p for p in path.split("/") if p]
    if not parts or parts[0] != "api":
        return None, False
    # Expect: api / <tag-or-tag-with-dashes> / <resource> / [...]
    if len(parts) < _MIN_PATH_PARTS:
        return None, False
    # Some plugin endpoints have nested tags (e.g., ['plugins', '<plugin>']).
    # The tag string from the spec is authoritative; just find <resource>.
    # Strategy: skip leading non-parameter segments until we've consumed the
    # tag's words and reached a resource segment.
    # Easier heuristic that works for NetBox: the resource is the first
    # segment after the segment that begins the tag's path-form.
    tag_form = tag.replace(" ", "-").lower()
    try:
        anchor = parts.index(tag_form)
    except ValueError:
        # Fall back: assume parts[1] is the tag, parts[2] is the resource.
        anchor = 1
    if anchor + 1 >= len(parts):
        return None, False
    resource = parts[anchor + 1]
    if _PARAM_SEGMENT.match(resource):
        return None, False
    remainder = parts[anchor + 2 :]
    is_collection = all(not _PARAM_SEGMENT.match(p) for p in remainder) and not remainder
    # If the only remaining segment is `{id}` it's the per-item path:
    if len(remainder) == 1 and _PARAM_SEGMENT.match(remainder[0]):
        is_collection = False
    return resource, is_collection


_CRUD_MAP: dict[tuple[HttpMethod, bool], str] = {
    (HttpMethod.GET, False): "list",
    (HttpMethod.GET, True): "get",
    (HttpMethod.POST, False): "create",
    (HttpMethod.PATCH, True): "update",
    (HttpMethod.PUT, True): "replace",
    (HttpMethod.DELETE, True): "delete",
}


def _classify(
    method: HttpMethod,
    path: str,
    schema_op: SchemaOperation,
    resource_name: str,
) -> str:
    has_id = "{id}" in path
    extra_path_segments = path.rstrip("/").split("/")[-1]
    is_action_endpoint = has_id and not _PARAM_SEGMENT.match(extra_path_segments)

    if is_action_endpoint:
        return "custom"

    return _CRUD_MAP.get((method, has_id), "custom")


def _attach(
    resource: _MutableResource,
    classification: str,
    op: Operation,
    is_collection_path: bool,  # kept for future heuristics
) -> None:
    match classification:
        case "list":
            resource.list_op = op
        case "get":
            resource.get_op = op
        case "create":
            resource.create_op = op
        case "update":
            resource.update_op = op
        case "replace":
            resource.replace_op = op
        case "delete":
            resource.delete_op = op
        case _:
            resource.custom_actions.append(op)


def _to_model_operation(
    path: str,
    http_method: HttpMethod,
    schema_op: SchemaOperation,
    item: PathItem,
) -> Operation:
    if schema_op.operation_id is None:
        # Synthesize one — operationId is required in practice but we degrade
        # gracefully rather than crashing on hand-rolled schemas.
        synthesized = f"{http_method.value.lower()}_{path.strip('/').replace('/', '_')}"
        operation_id = synthesized
    else:
        operation_id = schema_op.operation_id

    parameters = [_to_model_parameter(p) for p in (*item.parameters, *schema_op.parameters)]

    return Operation(
        operation_id=operation_id,
        http_method=http_method,
        path=path,
        summary=schema_op.summary,
        description=schema_op.description,
        parameters=parameters,
        has_request_body=schema_op.request_body is not None,
    )


def _to_model_parameter(p: SchemaParameter) -> Parameter:
    enum_values: list[str] | None = None
    primitive = PrimitiveType.UNKNOWN
    if p.schema_ is not None:
        primitive = _primitive(p.schema_)
        if p.schema_.enum:
            enum_values = [str(v) for v in p.schema_.enum]
    return Parameter(
        name=p.name,
        location=ParameterLocation(p.in_.value),
        primitive=primitive,
        required=p.required,
        description=p.description,
        enum=enum_values,
    )


def _primitive(schema: SchemaObject) -> PrimitiveType:
    if schema.type is None:
        return PrimitiveType.UNKNOWN
    try:
        return PrimitiveType(schema.type)
    except ValueError:
        return PrimitiveType.UNKNOWN


def _tag_description(name: str, doc: OpenAPIDocument) -> str | None:
    for tag in doc.tags:
        if tag.name == name:
            return tag.description
    return None


def _finalize_resource(name: str, m: _MutableResource) -> Resource:
    return Resource(
        name=name,
        list_op=m.list_op,
        get_op=m.get_op,
        create_op=m.create_op,
        update_op=m.update_op,
        replace_op=m.replace_op,
        delete_op=m.delete_op,
        custom_actions=list(m.custom_actions),
    )
