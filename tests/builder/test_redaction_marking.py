"""Phase 4d: build-time collection of sensitive request-body field paths."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nsc.builder.build import build_command_model
from nsc.schema.loader import LoadedSchema, load_schema
from nsc.schema.models import OpenAPIDocument


def _doc_with_post(path: str, body_schema: dict[str, Any]) -> OpenAPIDocument:
    """Build a minimal OpenAPIDocument with one POST operation."""
    return OpenAPIDocument.model_validate(
        {
            "openapi": "3.0.0",
            "info": {"title": "T", "version": "0"},
            "paths": {
                path: {
                    "post": {
                        "operationId": "create",
                        "tags": ["t"],
                        "requestBody": {"content": {"application/json": {"schema": body_schema}}},
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
            "tags": [{"name": "t"}],
        }
    )


def _loaded(doc: OpenAPIDocument) -> LoadedSchema:
    return LoadedSchema(source="test", body=b"", hash="sha256:test", document=doc)


def _create_op_body(model_doc: OpenAPIDocument):
    cm = build_command_model(_loaded(model_doc))
    op = cm.tags["t"].resources["t"].create_op
    assert op is not None
    assert op.request_body is not None
    return op.request_body


def test_canonical_field_name_is_marked() -> None:
    body = _create_op_body(
        _doc_with_post(
            "/api/t/t/",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "password": {"type": "string"},
                },
            },
        )
    )
    assert body.sensitive_paths == ("password",)


def test_format_password_is_marked_even_with_innocent_name() -> None:
    body = _create_op_body(
        _doc_with_post(
            "/api/t/t/",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "auth_blob": {"type": "string", "format": "password"},
                },
            },
        )
    )
    assert body.sensitive_paths == ("auth_blob",)


def test_canonical_name_is_case_insensitive() -> None:
    body = _create_op_body(
        _doc_with_post(
            "/api/t/t/",
            {
                "type": "object",
                "properties": {
                    "PassWord": {"type": "string"},
                    "API_KEY": {"type": "string"},
                },
            },
        )
    )
    assert set(body.sensitive_paths) == {"PassWord", "API_KEY"}


def test_all_canonical_names_match() -> None:
    canonical = [
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "private_key",
        "passphrase",
        "client_secret",
    ]
    props = {n: {"type": "string"} for n in canonical}
    body = _create_op_body(_doc_with_post("/api/t/t/", {"type": "object", "properties": props}))
    assert set(body.sensitive_paths) == set(canonical)


def test_nested_object_field_is_marked_with_dotted_path() -> None:
    body = _create_op_body(
        _doc_with_post(
            "/api/t/t/",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "auth": {
                        "type": "object",
                        "properties": {
                            "username": {"type": "string"},
                            "password": {"type": "string"},
                        },
                    },
                },
            },
        )
    )
    assert body.sensitive_paths == ("auth.password",)


def test_array_of_objects_uses_field_name_without_indices() -> None:
    body = _create_op_body(
        _doc_with_post(
            "/api/t/t/",
            {
                "type": "object",
                "properties": {
                    "members": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "username": {"type": "string"},
                                "secret": {"type": "string"},
                            },
                        },
                    }
                },
            },
        )
    )
    # Spec §4.5: "Arrays of objects redact per element." Path stored without
    # array indices; redactor (Task 5) applies it per element.
    assert body.sensitive_paths == ("members.secret",)


def test_no_sensitive_fields_yields_empty_tuple() -> None:
    body = _create_op_body(
        _doc_with_post(
            "/api/t/t/",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "slug": {"type": "string"},
                },
            },
        )
    )
    assert body.sensitive_paths == ()


def test_paths_are_sorted_for_deterministic_output() -> None:
    body = _create_op_body(
        _doc_with_post(
            "/api/t/t/",
            {
                "type": "object",
                "properties": {
                    "secret": {"type": "string"},
                    "password": {"type": "string"},
                    "token": {"type": "string"},
                    "name": {"type": "string"},
                },
            },
        )
    )
    assert body.sensitive_paths == ("password", "secret", "token")


def test_bundled_netbox_schema_marks_users_users_password() -> None:
    """Smoke test against the real bundled NetBox snapshot.

    The bundled snapshot is at nsc/schemas/bundled/*.json.gz. This proves the
    walker survives real-world OpenAPI shapes (oneOf branches, $ref cycles).
    """
    bundled = next(Path("nsc/schemas/bundled").glob("*.json*"))
    cm = build_command_model(load_schema(str(bundled)))
    users_resource = cm.tags["users"].resources["users"]
    create_op = users_resource.create_op
    assert create_op is not None
    assert create_op.request_body is not None
    # NetBox's users API has a `password` field on writable representations.
    assert "password" in create_op.request_body.sensitive_paths
