"""Load an OpenAPI schema from a URL or local file path."""

from __future__ import annotations

import gzip
from dataclasses import dataclass
from pathlib import Path

import httpx

from nsc.schema.hashing import canonical_sha256
from nsc.schema.models import OpenAPIDocument

_HTTP_ERROR_THRESHOLD = 400


class SchemaLoadError(Exception):
    """Raised when a schema cannot be loaded or parsed."""


@dataclass(frozen=True, slots=True)
class LoadedSchema:
    """A parsed OpenAPI document plus the hash of its canonical body."""

    source: str
    body: bytes
    hash: str
    document: OpenAPIDocument


def load_schema(source: str, *, verify_ssl: bool = True, timeout: float = 30.0) -> LoadedSchema:
    """Load and parse the schema at `source`.

    `source` is either an `http(s)://` URL or a local filesystem path. The path
    can be absolute or relative to the current working directory.
    """
    body = _fetch_body(source, verify_ssl=verify_ssl, timeout=timeout)
    if source.endswith(".gz"):
        try:
            body = gzip.decompress(body)
        except gzip.BadGzipFile as exc:
            raise SchemaLoadError(f"{source}: not valid gzip ({exc})") from exc
    try:
        h = canonical_sha256(body)
    except ValueError as exc:
        raise SchemaLoadError(f"{source}: not valid JSON ({exc})") from exc
    try:
        doc = OpenAPIDocument.model_validate_json(body)
    except Exception as exc:
        raise SchemaLoadError(f"{source}: schema does not match expected shape: {exc}") from exc
    return LoadedSchema(source=source, body=body, hash=h, document=doc)


def _fetch_body(source: str, *, verify_ssl: bool, timeout: float) -> bytes:
    if source.startswith(("http://", "https://")):
        try:
            response = httpx.get(source, verify=verify_ssl, timeout=timeout, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise SchemaLoadError(f"{source}: request failed ({exc})") from exc
        if response.status_code >= _HTTP_ERROR_THRESHOLD:
            raise SchemaLoadError(f"{source}: HTTP {response.status_code}")
        return response.content
    p = Path(source)
    if not p.exists():
        raise SchemaLoadError(f"{source}: not found")
    return p.read_bytes()
