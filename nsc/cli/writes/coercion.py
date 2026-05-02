"""Shared boolean-string coercion sets (preflight + apply must agree)."""

from __future__ import annotations

TRUTHY: frozenset[str] = frozenset({"true", "1", "yes"})
FALSY: frozenset[str] = frozenset({"false", "0", "no"})
BOOL_STRINGS: frozenset[str] = TRUTHY | FALSY

__all__ = ["BOOL_STRINGS", "FALSY", "TRUTHY"]
