"""Single source of truth for sensitive HTTP header names."""

from __future__ import annotations

SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {"authorization", "cookie", "x-api-key", "proxy-authorization"}
)

__all__ = ["SENSITIVE_HEADERS"]
