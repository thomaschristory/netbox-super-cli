from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from nsc.http.errors import NetBoxAPIError
from nsc.savedfilters.store import SAVED_FILTERS_PATH, NativeSavedFilterStore


class _StubResolver:
    def __init__(self, object_type: str | None) -> None:
        self._object_type = object_type
        self.calls: list[str] = []

    def resolve(self, list_path: str) -> str | None:
        self.calls.append(list_path)
        return self._object_type


class _FakeFallback:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], dict[str, dict[str, str]]] = {}
        self.list_calls: list[tuple[str, str]] = []
        self.save_calls: list[tuple[str, str, str, dict[str, str]]] = []
        self.delete_calls: list[tuple[str, str, str]] = []

    def list(self, tag: str, resource: str) -> dict[str, dict[str, str]]:
        self.list_calls.append((tag, resource))
        return self.store.get((tag, resource), {})

    def save(self, tag: str, resource: str, name: str, params: dict[str, str]) -> None:
        self.save_calls.append((tag, resource, name, params))
        self.store.setdefault((tag, resource), {})[name] = params

    def delete(self, tag: str, resource: str, name: str) -> None:
        self.delete_calls.append((tag, resource, name))
        self.store.get((tag, resource), {}).pop(name, None)


class _FakeClient:
    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        self.records = records or []
        self.posts: list[tuple[str, Any]] = []
        self.patches: list[tuple[str, Any]] = []
        self.deletes: list[str] = []
        self.paginate_calls: list[tuple[str, dict[str, Any] | None]] = []
        self.fail = False

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        self.paginate_calls.append((path, params))
        if self.fail:
            raise NetBoxAPIError(status_code=500, url=path, body_snippet="", headers={})
        name = (params or {}).get("name")
        for rec in self.records:
            if name is None or rec.get("name") == name:
                yield rec

    def post(self, path: str, *, json: Any = None, **kw: Any) -> dict[str, Any]:
        self.posts.append((path, json))
        return {"id": 99, **(json or {})}

    def patch(self, path: str, *, json: Any = None, **kw: Any) -> dict[str, Any]:
        self.patches.append((path, json))
        return {}

    def delete(self, path: str, **kw: Any) -> dict[str, Any]:
        self.deletes.append(path)
        return {}


def _store(client: _FakeClient, fallback: _FakeFallback, ot: str | None = "dcim.device", **kw: Any):
    return NativeSavedFilterStore(client, fallback, resolver=_StubResolver(ot), **kw)


def test_list_reads_saved_filters_for_the_object_type() -> None:
    client = _FakeClient(
        [
            {"id": 1, "name": "active", "parameters": {"status": ["active"]}},
            {"id": 2, "name": "leafs", "parameters": {"role": ["leaf"]}},
        ]
    )
    store = _store(client, _FakeFallback())
    result = store.list("/api/dcim/devices/", "dcim", "devices")
    assert result == {"active": {"status": "active"}, "leafs": {"role": "leaf"}}
    assert client.paginate_calls == [(SAVED_FILTERS_PATH, {"object_type": "dcim.device"})]


def test_save_creates_a_new_saved_filter_when_absent() -> None:
    client = _FakeClient([])
    store = _store(client, _FakeFallback())
    store.save("/api/dcim/devices/", "dcim", "devices", "active", {"status": "active"})
    assert len(client.posts) == 1
    path, body = client.posts[0]
    assert path == SAVED_FILTERS_PATH
    assert body["name"] == "active"
    assert body["object_types"] == ["dcim.device"]
    assert body["parameters"] == {"status": ["active"]}
    assert body["slug"]
    assert body["shared"] is True
    assert body["enabled"] is True


def test_save_patches_existing_filter_matched_by_name() -> None:
    client = _FakeClient([{"id": 7, "name": "active", "parameters": {"status": ["offline"]}}])
    store = _store(client, _FakeFallback())
    store.save("/api/dcim/devices/", "dcim", "devices", "active", {"status": "active"})
    assert client.posts == []
    assert len(client.patches) == 1
    path, body = client.patches[0]
    assert path == f"{SAVED_FILTERS_PATH}7/"
    assert body["parameters"] == {"status": ["active"]}
    # name/slug are not rewritten on update, so a web-UI-created slug survives.
    assert "slug" not in body


def test_delete_removes_filter_matched_by_name() -> None:
    client = _FakeClient([{"id": 7, "name": "active", "parameters": {}}])
    store = _store(client, _FakeFallback())
    store.delete("/api/dcim/devices/", "dcim", "devices", "active")
    assert client.deletes == [f"{SAVED_FILTERS_PATH}7/"]


def test_delete_is_a_noop_when_name_not_found() -> None:
    client = _FakeClient([])
    store = _store(client, _FakeFallback())
    store.delete("/api/dcim/devices/", "dcim", "devices", "ghost")
    assert client.deletes == []


def test_object_type_unresolved_uses_fallback_for_all_ops() -> None:
    client = _FakeClient([])
    fallback = _FakeFallback()
    store = _store(client, fallback, ot=None)
    store.save("/api/x/y/", "x", "y", "n", {"a": "b"})
    store.list("/api/x/y/", "x", "y")
    store.delete("/api/x/y/", "x", "y", "n")
    assert fallback.save_calls and fallback.list_calls and fallback.delete_calls
    assert client.posts == [] and client.deletes == []


def test_api_failure_falls_back_and_reports() -> None:
    client = _FakeClient([])
    client.fail = True
    fallback = _FakeFallback()
    errors: list[str] = []
    store = _store(client, fallback, on_error=errors.append)
    result = store.list("/api/dcim/devices/", "dcim", "devices")
    assert result == {}
    assert fallback.list_calls == [("dcim", "devices")]
    assert errors  # the failure was surfaced, not swallowed silently


def test_save_api_failure_falls_back_to_local_write() -> None:
    client = _FakeClient([])
    client.fail = True  # the name-lookup paginate raises before any write
    fallback = _FakeFallback()
    errors: list[str] = []
    store = _store(client, fallback, on_error=errors.append)
    store.save("/api/dcim/devices/", "dcim", "devices", "active", {"status": "active"})
    assert fallback.save_calls == [("dcim", "devices", "active", {"status": "active"})]
    assert errors


def test_delete_api_failure_falls_back_to_local_delete() -> None:
    client = _FakeClient([])
    client.fail = True  # the name-lookup paginate raises before any delete
    fallback = _FakeFallback()
    errors: list[str] = []
    store = _store(client, fallback, on_error=errors.append)
    store.delete("/api/dcim/devices/", "dcim", "devices", "active")
    assert fallback.delete_calls == [("dcim", "devices", "active")]
    assert errors


def test_list_warns_on_duplicate_names_and_keeps_first() -> None:
    # NetBox permits same-named filters; list() keeps the first deterministically
    # (matching _find's save/delete target) and surfaces the ambiguity.
    client = _FakeClient(
        [
            {"id": 1, "name": "dup", "parameters": {"status": ["active"]}},
            {"id": 2, "name": "dup", "parameters": {"status": ["offline"]}},
        ]
    )
    errors: list[str] = []
    store = _store(client, _FakeFallback(), on_error=errors.append)
    result = store.list("/api/dcim/devices/", "dcim", "devices")
    assert result == {"dup": {"status": "active"}}
    assert any("dup" in e for e in errors)
