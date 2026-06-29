"""Resolve the available NetBox tags for tag-picker widgets (#134).

Tags are global (not object-type scoped), so a single fetch of
``/api/extras/tags/`` is cached for the session. Mirrors the other resolvers:
returns ``None`` (never raises) when the API can't be reached, so the tag widget
degrades to free-text input. A writable ``tags`` PATCH wants a list of
``{name, slug}`` objects, so both are carried.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from nsc.http.errors import NetBoxAPIError, NetBoxClientError
from nsc.output.colors import normalize_hex

_TAGS_PATH = "/api/extras/tags/"


class _ClientLike(Protocol):
    def paginate(
        self, path: str, params: dict[str, Any] | None = ..., *, limit: int | None = ...
    ) -> Any: ...


@dataclass(frozen=True)
class TagDef:
    name: str
    slug: str
    color: str | None = None

    @property
    def label(self) -> str:
        return self.name


class TagsResolver:
    """Fetches the global tag list once and caches it for the session."""

    def __init__(self, client: _ClientLike) -> None:
        self._client = client
        self._cache: tuple[TagDef, ...] | None = None

    def resolve(self) -> tuple[TagDef, ...] | None:
        """All tags, or ``None`` if the API can't be reached."""
        if self._cache is not None:
            return self._cache
        try:
            records = list(self._client.paginate(_TAGS_PATH))
        except (NetBoxAPIError, NetBoxClientError):
            return None
        tags = tuple(
            TagDef(
                name=str(rec.get("name", "")),
                slug=str(rec.get("slug", "")),
                color=normalize_hex(rec.get("color")),
            )
            for rec in records
        )
        self._cache = tags
        return tags
