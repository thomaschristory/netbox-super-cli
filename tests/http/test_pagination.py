from __future__ import annotations

from typing import Any

from nsc.http.pagination import Pager


class _Pages:
    def __init__(self, pages: dict[str, dict[str, Any]]) -> None:
        self._pages = pages
        self.requests: list[tuple[str, dict[str, Any] | None]] = []

    def __call__(self, path: str, params: dict[str, Any] | None) -> dict[str, Any]:
        self.requests.append((path, params))
        key = path if not params else f"{path}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
        return self._pages[key]


def _two_pages() -> _Pages:
    return _Pages(
        {
            "/api/x/?status=active": {
                "count": 3,
                "next": "https://nb.example/api/x/?status=active&offset=2",
                "results": [{"id": 1}, {"id": 2}],
            },
            "/api/x/?status=active&offset=2": {
                "count": 3,
                "next": None,
                "results": [{"id": 3}],
            },
        }
    )


def test_pager_is_lazy_until_first_next() -> None:
    fetch = _two_pages()
    pager = Pager(fetch, "/api/x/", {"status": "active"})
    assert fetch.requests == []
    assert pager.total is None
    assert pager.has_more is True


def test_pager_follows_next_and_records_total() -> None:
    fetch = _two_pages()
    pager = Pager(fetch, "/api/x/", {"status": "active"})
    assert [r["id"] for r in pager] == [1, 2, 3]
    assert pager.total == 3
    assert pager.has_more is False
    assert fetch.requests[1] == ("/api/x/", {"status": "active", "offset": "2"})


def test_pager_resumes_across_partial_reads_without_refetching() -> None:
    fetch = _two_pages()
    pager = Pager(fetch, "/api/x/", {"status": "active"})
    first = [next(pager), next(pager)]
    assert [r["id"] for r in first] == [1, 2]
    assert len(fetch.requests) == 1
    assert pager.total == 3
    assert pager.has_more is True
    assert [r["id"] for r in pager] == [3]
    assert len(fetch.requests) == 2


def test_pager_limit_stops_without_fetching_next_page() -> None:
    fetch = _two_pages()
    pager = Pager(fetch, "/api/x/", {"status": "active"}, limit=2)
    assert [r["id"] for r in pager] == [1, 2]
    assert len(fetch.requests) == 1
    assert pager.has_more is True


def test_pager_handles_missing_count_and_results() -> None:
    fetch = _Pages({"/api/x/": {}})
    pager = Pager(fetch, "/api/x/", None)
    assert list(pager) == []
    assert pager.total is None
    assert pager.has_more is False
