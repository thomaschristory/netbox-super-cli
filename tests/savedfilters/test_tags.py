from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from nsc.http.errors import NetBoxAPIError
from nsc.savedfilters.tags import TagDef, TagsResolver

_TAGS = [
    {"id": 1, "name": "prod", "slug": "prod", "color": "4caf50"},
    {"id": 2, "name": "Edge", "slug": "edge", "color": "#FF0000"},
    {"id": 3, "name": "blank", "slug": "blank", "color": ""},
]


class _FakeClient:
    def __init__(self, tags: list[dict[str, Any]], *, fail: bool = False) -> None:
        self._tags = tags
        self._fail = fail
        self.calls: list[str] = []

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        self.calls.append(path)
        if self._fail:
            raise NetBoxAPIError(status_code=404, url=path, body_snippet="", headers={})
        yield from self._tags


def test_resolve_returns_tag_defs() -> None:
    tags = TagsResolver(_FakeClient(_TAGS)).resolve()
    assert tags is not None
    assert TagDef(name="prod", slug="prod", color="4caf50") in tags


def test_resolve_normalizes_color() -> None:
    tags = TagsResolver(_FakeClient(_TAGS)).resolve()
    assert tags is not None
    by_slug = {t.slug: t for t in tags}
    assert by_slug["edge"].color == "ff0000"
    assert by_slug["blank"].color is None


def test_resolve_caches() -> None:
    client = _FakeClient(_TAGS)
    resolver = TagsResolver(client)
    resolver.resolve()
    resolver.resolve()
    assert client.calls == ["/api/extras/tags/"]


def test_resolve_none_on_api_error() -> None:
    assert TagsResolver(_FakeClient(_TAGS, fail=True)).resolve() is None
