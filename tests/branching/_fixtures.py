from __future__ import annotations

from typing import Any


class FakeProfile:
    def __init__(self, url: str = "https://nb.example") -> None:
        self.url = url
        self.token = "tok"
        self.verify_ssl = True
        self.timeout = 5.0


def branch_json(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": 3,
        "name": "my-change",
        "schema_id": "abcd1234",
        "status": {"value": "ready", "label": "Ready"},
        "owner": {"id": 1, "username": "admin"},
        "description": "",
        "last_sync": None,
    }
    data.update(over)
    return data


def job_json(status: str = "pending", **over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": 7,
        "url": "https://nb.example/api/core/jobs/7/",
        "status": {"value": status, "label": status.title()},
        "error": "",
        "log_entries": [],
    }
    data.update(over)
    return data


def page(*results: dict[str, Any], next_url: str | None = None) -> dict[str, Any]:
    return {"count": len(results), "next": next_url, "previous": None, "results": list(results)}


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now
