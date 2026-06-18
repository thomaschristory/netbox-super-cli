"""Tests for `nsc.schema.loader`."""

from __future__ import annotations

import gzip as _gzip
import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx

from nsc.schema.loader import LoadedSchema, SchemaLoadError, load_schema

MINIMAL = {
    "openapi": "3.0.3",
    "info": {"title": "NetBox", "version": "4.1.0"},
    "paths": {},
    "components": {"schemas": {}},
    "tags": [],
}


def test_loads_from_local_file(tmp_path: Path) -> None:
    p = tmp_path / "schema.json"
    p.write_text(json.dumps(MINIMAL))
    loaded = load_schema(str(p))
    assert isinstance(loaded, LoadedSchema)
    assert loaded.document.info.version == "4.1.0"
    assert loaded.source == str(p)
    assert len(loaded.hash) == 64


@respx.mock
def test_loads_from_https_url() -> None:
    url = "https://netbox.example.com/api/schema/?format=json"
    respx.get(url).mock(return_value=httpx.Response(200, json=MINIMAL))
    loaded = load_schema(url)
    assert loaded.document.info.title == "NetBox"
    assert loaded.source == url


def test_missing_file_raises() -> None:
    with pytest.raises(SchemaLoadError, match="not found"):
        load_schema("/no/such/file.json")


def test_non_json_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("not json")
    with pytest.raises(SchemaLoadError, match="not valid JSON"):
        load_schema(str(p))


@respx.mock
def test_http_error_raises_load_error() -> None:
    url = "https://netbox.example.com/api/schema/"
    respx.get(url).mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(SchemaLoadError, match="500"):
        load_schema(url)


def test_loads_from_gzipped_local_file(tmp_path: Path) -> None:
    p = tmp_path / "schema.json.gz"
    p.write_bytes(_gzip.compress(json.dumps(MINIMAL).encode("utf-8")))
    loaded = load_schema(str(p))
    assert loaded.document.info.title == "NetBox"
    assert loaded.source == str(p)
    # Hash is computed against the decompressed body — should match the
    # hash of the same content stored uncompressed.
    p2 = tmp_path / "schema.json"
    p2.write_text(json.dumps(MINIMAL))
    loaded2 = load_schema(str(p2))
    assert loaded.hash == loaded2.hash


def test_invalid_gzip_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.json.gz"
    p.write_bytes(b"not really gzipped")
    with pytest.raises(SchemaLoadError, match="not valid gzip"):
        load_schema(str(p))


def test_gzip_bomb_local_file_rejected(tmp_path: Path) -> None:
    """Security audit L2: decompressed schema bigger than the cap is rejected."""
    p = tmp_path / "bomb.json.gz"
    p.write_bytes(_gzip.compress(b"\x00" * (200 * 1024 * 1024)))
    with pytest.raises(SchemaLoadError, match="exceeds"):
        load_schema(str(p))


class _CountingStream(httpx.SyncByteStream):
    """A lazy byte stream that records how many chunks were actually pulled."""

    def __init__(self, chunk: bytes, count: int) -> None:
        self._chunk = chunk
        self._count = count
        self.pulled = 0

    def __iter__(self) -> Iterator[bytes]:
        for _ in range(self._count):
            self.pulled += 1
            yield self._chunk

    def close(self) -> None:
        pass


@respx.mock
def test_oversized_http_body_aborts_mid_stream() -> None:
    """Security audit L2: an over-cap HTTP body is rejected before the whole body is read."""
    url = "https://netbox.example.com/api/schema/?format=json"
    stream = _CountingStream(b"\x00" * (8 * 1024 * 1024), count=32)  # 256 MB if fully drained
    respx.get(url).mock(return_value=httpx.Response(200, stream=stream))
    with pytest.raises(SchemaLoadError, match="exceeds"):
        load_schema(url)
    assert stream.pulled < 32  # aborted early, did not buffer the full body


@respx.mock
def test_content_encoding_gzip_bomb_rejected() -> None:
    """Security audit L2: a Content-Encoding: gzip bomb is bounded, not inflated whole."""
    url = "https://netbox.example.com/api/schema/?format=json"
    bomb = _gzip.compress(b"\x00" * (200 * 1024 * 1024))
    respx.get(url).mock(
        return_value=httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=bomb)
    )
    with pytest.raises(SchemaLoadError, match="exceeds"):
        load_schema(url)


@respx.mock
def test_gzip_bomb_http_url_rejected() -> None:
    """Security audit L2: a .gz URL whose body decompresses past the cap is rejected."""
    url = "https://netbox.example.com/api/schema.json.gz"
    bomb = _gzip.compress(b"\x00" * (200 * 1024 * 1024))
    respx.get(url).mock(return_value=httpx.Response(200, content=bomb))
    with pytest.raises(SchemaLoadError, match="exceeds"):
        load_schema(url)


@respx.mock
def test_unsupported_content_encoding_rejected() -> None:
    url = "https://netbox.example.com/api/schema/?format=json"
    respx.get(url).mock(
        return_value=httpx.Response(200, headers={"Content-Encoding": "br"}, content=b"{}")
    )
    with pytest.raises(SchemaLoadError, match="unsupported Content-Encoding"):
        load_schema(url)


def test_truncated_gzip_rejected(tmp_path: Path) -> None:
    """Security audit L2: a truncated gzip stream errors instead of partial-decoding."""
    full = _gzip.compress(json.dumps(MINIMAL).encode("utf-8"))
    p = tmp_path / "trunc.json.gz"
    p.write_bytes(full[: len(full) // 2])
    with pytest.raises(SchemaLoadError, match="gzip"):
        load_schema(str(p))


def test_multimember_gzip_trailing_data_rejected(tmp_path: Path) -> None:
    """A multi-member .gz would silently drop members; reject the trailing data instead."""
    p = tmp_path / "multi.json.gz"
    p.write_bytes(_gzip.compress(b'{"a": 1}') + _gzip.compress(b'{"b": 2}'))
    with pytest.raises(SchemaLoadError, match="trailing"):
        load_schema(str(p))
