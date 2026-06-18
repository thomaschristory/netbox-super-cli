"""Load an OpenAPI schema from a URL or local file path."""

from __future__ import annotations

import zlib
from collections.abc import Iterator
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
        body = _bounded_decompress(body, wbits=_GZIP_WBITS, source=source)
    try:
        h = canonical_sha256(body)
    except ValueError as exc:
        raise SchemaLoadError(f"{source}: not valid JSON ({exc})") from exc
    try:
        doc = OpenAPIDocument.model_validate_json(body)
    except Exception as exc:
        raise SchemaLoadError(f"{source}: schema does not match expected shape: {exc}") from exc
    return LoadedSchema(source=source, body=body, hash=h, document=doc)


def _bounded_decompress(data: bytes, *, wbits: int, source: str) -> bytes:
    """Inflate `data`, refusing oversized, truncated, or trailing-data streams.

    An incremental decompressor capped at `_MAX_SCHEMA_BYTES` means a small
    highly compressible payload cannot expand to gigabytes and exhaust memory.
    Leftover compressed input (`unconsumed_tail`) signals an over-cap stream; a
    decompressor that never reaches end-of-stream (`eof`) signals a truncated
    body; `unused_data` signals trailing bytes after the stream we won't accept.
    """
    decompressor = zlib.decompressobj(wbits=wbits)
    try:
        out = decompressor.decompress(data, _MAX_SCHEMA_BYTES)
        # Leftover compressed input means the output hit the cap: a bomb. Check
        # this BEFORE flush(), which would otherwise inflate the tail unbounded.
        if decompressor.unconsumed_tail:
            raise SchemaLoadError(
                f"{source}: decompressed schema exceeds {_MAX_SCHEMA_BYTES} bytes"
            )
        out += decompressor.flush()
    except zlib.error as exc:
        raise SchemaLoadError(f"{source}: not valid gzip ({exc})") from exc
    if not decompressor.eof:
        raise SchemaLoadError(f"{source}: incomplete or truncated gzip stream")
    if decompressor.unused_data:
        raise SchemaLoadError(f"{source}: unexpected trailing data after gzip stream")
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


def _read_capped(chunks: Iterator[bytes], source: str) -> bytes:
    """Accumulate `chunks` into a single buffer, aborting past `_MAX_SCHEMA_BYTES`."""
    out: list[bytes] = []
    total = 0
    for chunk in chunks:
        total += len(chunk)
        if total > _MAX_SCHEMA_BYTES:
            raise SchemaLoadError(f"{source}: response body exceeds {_MAX_SCHEMA_BYTES} bytes")
        out.append(chunk)
    return b"".join(out)


def _decode_content_encoding(raw: bytes, encoding: str, source: str) -> bytes:
    """Decode an HTTP transport Content-Encoding through the bounded decompressor.

    We request `Accept-Encoding: identity`, so a well-behaved server returns the
    body verbatim. A server that compresses anyway only gets gzip decoded (via the
    memory-bounded path); anything else is refused rather than decoded unbounded.
    """
    normalized = encoding.lower().strip()
    if normalized in ("", "identity"):
        return raw
    if normalized in ("gzip", "x-gzip"):
        return _bounded_decompress(raw, wbits=_GZIP_WBITS, source=source)
    raise SchemaLoadError(f"{source}: unsupported Content-Encoding {encoding!r}")


def _fetch_http_body(source: str, *, verify_ssl: bool, timeout: float) -> bytes:
    try:
        with httpx.stream(
            "GET",
            source,
            verify=verify_ssl,
            timeout=timeout,
            follow_redirects=True,
            headers={"Accept-Encoding": "identity"},
        ) as response:
            if response.status_code >= _HTTP_ERROR_THRESHOLD:
                raise SchemaLoadError(f"{source}: HTTP {response.status_code}")
            # iter_raw yields the un-decoded wire bytes so the cap bounds peak
            # memory; iter_bytes would transparently inflate a Content-Encoding
            # bomb to gigabytes *before* the size check ran (security audit L2).
            raw = _read_capped(response.iter_raw(), source)
            encoding = response.headers.get("content-encoding", "")
            return _decode_content_encoding(raw, encoding, source)
    except httpx.HTTPError as exc:
        raise SchemaLoadError(f"{source}: request failed ({exc})") from exc
