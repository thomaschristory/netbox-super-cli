"""Load an OpenAPI schema from a URL or local file path."""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from pathlib import Path

import httpx

from nsc.schema.hashing import canonical_sha256
from nsc.schema.models import OpenAPIDocument

_HTTP_ERROR_THRESHOLD = 400

# Cap on both the fetched body and any gzip-decompressed output. NetBox's
# OpenAPI document is a few MB; 64 MB leaves generous headroom while refusing
# decompression bombs and oversized/MITM'd remote bodies (security audit L2).
_MAX_SCHEMA_BYTES = 64 * 1024 * 1024
_GZIP_WBITS = 16 + zlib.MAX_WBITS


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
        body = _bounded_gunzip(body, source)
    try:
        h = canonical_sha256(body)
    except ValueError as exc:
        raise SchemaLoadError(f"{source}: not valid JSON ({exc})") from exc
    try:
        doc = OpenAPIDocument.model_validate_json(body)
    except Exception as exc:
        raise SchemaLoadError(f"{source}: schema does not match expected shape: {exc}") from exc
    return LoadedSchema(source=source, body=body, hash=h, document=doc)


def _bounded_gunzip(body: bytes, source: str) -> bytes:
    """Gunzip `body`, refusing output larger than `_MAX_SCHEMA_BYTES`.

    Uses an incremental decompressor capped at the limit so a small highly
    compressible payload cannot expand to gigabytes and exhaust memory.
    """
    decompressor = zlib.decompressobj(wbits=_GZIP_WBITS)
    try:
        out = decompressor.decompress(body, _MAX_SCHEMA_BYTES)
    except zlib.error as exc:
        raise SchemaLoadError(f"{source}: not valid gzip ({exc})") from exc
    if decompressor.unconsumed_tail:
        raise SchemaLoadError(f"{source}: decompressed schema exceeds {_MAX_SCHEMA_BYTES} bytes")
    return out


def _fetch_body(source: str, *, verify_ssl: bool, timeout: float) -> bytes:
    if source.startswith(("http://", "https://")):
        return _fetch_http_body(source, verify_ssl=verify_ssl, timeout=timeout)
    p = Path(source)
    if not p.exists():
        raise SchemaLoadError(f"{source}: not found")
    if p.stat().st_size > _MAX_SCHEMA_BYTES:
        raise SchemaLoadError(f"{source}: schema file exceeds {_MAX_SCHEMA_BYTES} bytes")
    return p.read_bytes()


def _fetch_http_body(source: str, *, verify_ssl: bool, timeout: float) -> bytes:
    try:
        with httpx.stream(
            "GET", source, verify=verify_ssl, timeout=timeout, follow_redirects=True
        ) as response:
            if response.status_code >= _HTTP_ERROR_THRESHOLD:
                raise SchemaLoadError(f"{source}: HTTP {response.status_code}")
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > _MAX_SCHEMA_BYTES:
                    raise SchemaLoadError(
                        f"{source}: response body exceeds {_MAX_SCHEMA_BYTES} bytes"
                    )
                chunks.append(chunk)
            return b"".join(chunks)
    except httpx.HTTPError as exc:
        raise SchemaLoadError(f"{source}: request failed ({exc})") from exc
