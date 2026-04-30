"""Canonical hashing for schema bodies.

Two schema bodies that differ only in key ordering (or whitespace) hash to the
same value. This is the cache key for generated command-models.
"""

from __future__ import annotations

import hashlib
import json


def canonical_sha256(body: bytes) -> str:
    """Return the SHA-256 of `body` after JSON canonicalization.

    Raises:
        ValueError: if `body` is not valid JSON.
    """
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"schema body is not valid JSON: {exc}") from exc
    canonical = json.dumps(decoded, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
