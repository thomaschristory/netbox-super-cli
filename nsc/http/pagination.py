"""Lazy, resumable iteration over NetBox's ``count``/``next``/``results`` list pages."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

FetchPage = Callable[[str, dict[str, Any] | None], dict[str, Any]]


def _split_next(url: str) -> tuple[str, dict[str, Any] | None]:
    # next URLs are absolute; split them so respx (and httpx2) can match on
    # path + params independently rather than a raw string.
    parsed = urlsplit(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    return parsed.path, ({k: v[0] for k, v in qs.items()} if qs else None)


class Pager(Iterator[dict[str, Any]]):
    """Yields records page by page, fetching the next page only when needed.

    ``total`` is the server-reported ``count`` (``None`` until the first page
    arrives or when the server omits it). ``has_more`` says whether records
    remain server-side beyond those already yielded, without fetching.
    """

    def __init__(
        self,
        fetch: FetchPage,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        limit: int | None = None,
    ) -> None:
        self._fetch = fetch
        self._pending: tuple[str, dict[str, Any] | None] | None = (path, params)
        self._buffer: deque[dict[str, Any]] = deque()
        self._limit = limit
        self._emitted = 0
        self.total: int | None = None

    @property
    def has_more(self) -> bool:
        return bool(self._buffer) or self._pending is not None

    def __iter__(self) -> Pager:
        return self

    def __next__(self) -> dict[str, Any]:
        if self._limit is not None and self._emitted >= self._limit:
            raise StopIteration
        while not self._buffer:
            if self._pending is None:
                raise StopIteration
            self._load_page(*self._pending)
        self._emitted += 1
        return self._buffer.popleft()

    def _load_page(self, path: str, params: dict[str, Any] | None) -> None:
        payload = self._fetch(path, params)
        count = payload.get("count")
        if isinstance(count, int):
            self.total = count
        self._buffer.extend(payload.get("results") or [])
        nxt = payload.get("next")
        self._pending = _split_next(nxt) if isinstance(nxt, str) and nxt else None
