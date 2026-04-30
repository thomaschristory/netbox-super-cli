"""Pydantic models for the OpenAPI 3.x subset that NetBox emits and we consume.

Anything we don't explicitly model is tolerated via `extra="allow"` on root
container types, so vendor extensions and OpenAPI features we don't use can't
break parsing.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Tolerant(BaseModel):
    """Base for models that should accept unknown fields."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class ParameterIn(StrEnum):
    QUERY = "query"
    PATH = "path"
    HEADER = "header"
    COOKIE = "cookie"


class SchemaObject(_Tolerant):
    """A JSON Schema fragment as it appears inside an OpenAPI document.

    We only model the fields we use; the rest is preserved via `extra="allow"`.
    """

    type: str | None = None
    format: str | None = None
    enum: list[Any] | None = None
    items: SchemaObject | None = None
    properties: dict[str, SchemaObject] | None = None
    required: list[str] | None = None
    description: str | None = None
    ref: str | None = Field(default=None, alias="$ref")


class MediaType(_Tolerant):
    schema_: SchemaObject | None = Field(default=None, alias="schema")


class RequestBody(_Tolerant):
    description: str | None = None
    required: bool = False
    content: dict[str, MediaType] = Field(default_factory=dict)


class Response(_Tolerant):
    description: str | None = None
    content: dict[str, MediaType] = Field(default_factory=dict)


class Parameter(_Tolerant):
    name: str
    in_: ParameterIn = Field(alias="in")
    description: str | None = None
    required: bool = False
    schema_: SchemaObject | None = Field(default=None, alias="schema")


class Operation(_Tolerant):
    operation_id: str | None = Field(default=None, alias="operationId")
    summary: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    parameters: list[Parameter] = Field(default_factory=list)
    request_body: RequestBody | None = Field(default=None, alias="requestBody")
    responses: dict[str, Response] = Field(default_factory=dict)


class PathItem(_Tolerant):
    get: Operation | None = None
    put: Operation | None = None
    post: Operation | None = None
    delete: Operation | None = None
    patch: Operation | None = None
    options: Operation | None = None
    head: Operation | None = None
    parameters: list[Parameter] = Field(default_factory=list)


class Info(_Tolerant):
    title: str
    version: str
    description: str | None = None


class Tag(_Tolerant):
    name: str
    description: str | None = None


class Components(_Tolerant):
    schemas: dict[str, SchemaObject] = Field(default_factory=dict)


class OpenAPIDocument(_Tolerant):
    openapi: str
    info: Info
    paths: dict[str, PathItem] = Field(default_factory=dict)
    components: Components = Field(default_factory=Components)
    tags: list[Tag] = Field(default_factory=list)
