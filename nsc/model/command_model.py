"""The normalized command-model.

This module imports nothing from `nsc.cli`, `nsc.http`, Typer, Rich, or any
other framework. It is pure data plus a few traversal helpers. Anything else
in `nsc/` that needs the command tree depends on this module — and only this
module — for it.
"""

from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class HttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"
    PATCH = "PATCH"
    PUT = "PUT"
    DELETE = "DELETE"
    OPTIONS = "OPTIONS"
    HEAD = "HEAD"


class ParameterLocation(StrEnum):
    QUERY = "query"
    PATH = "path"
    HEADER = "header"
    COOKIE = "cookie"
    BODY = "body"


class PrimitiveType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
    UNKNOWN = "unknown"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Parameter(_Frozen):
    name: str
    location: ParameterLocation
    primitive: PrimitiveType = PrimitiveType.UNKNOWN
    required: bool = False
    description: str | None = None
    enum: list[str] | None = None


class Operation(_Frozen):
    operation_id: str
    http_method: HttpMethod
    path: str
    summary: str | None = None
    description: str | None = None
    parameters: list[Parameter] = Field(default_factory=list)
    has_request_body: bool = False


class Resource(_Frozen):
    name: str
    list_op: Operation | None = None
    get_op: Operation | None = None
    create_op: Operation | None = None
    update_op: Operation | None = None
    replace_op: Operation | None = None
    delete_op: Operation | None = None
    custom_actions: list[Operation] = Field(default_factory=list)


class Tag(_Frozen):
    name: str
    description: str | None = None
    resources: dict[str, Resource] = Field(default_factory=dict)


class CommandModel(_Frozen):
    """The full normalized tree: tags → resources → operations."""

    info_title: str
    info_version: str
    schema_hash: str
    tags: dict[str, Tag] = Field(default_factory=dict)

    def iter_operations(self) -> Iterator[tuple[str, str, Operation]]:
        """Yield `(tag, resource, operation)` triples in deterministic order."""
        for tag_name in sorted(self.tags):
            tag = self.tags[tag_name]
            for resource_name in sorted(tag.resources):
                resource = tag.resources[resource_name]
                for op in (
                    resource.list_op,
                    resource.get_op,
                    resource.create_op,
                    resource.update_op,
                    resource.replace_op,
                    resource.delete_op,
                ):
                    if op is not None:
                        yield (tag_name, resource_name, op)
                for op in resource.custom_actions:
                    yield (tag_name, resource_name, op)
