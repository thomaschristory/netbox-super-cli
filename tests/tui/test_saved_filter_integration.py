"""`NscTuiApp` saved-search methods routed through the native SavedFilter store."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from nsc.config.models import Config
from nsc.config.saved_searches import ConfigFileSavedSearchStore
from nsc.model.command_model import CommandModel, Operation, Resource, Tag
from nsc.savedfilters.store import SAVED_FILTERS_PATH, NativeSavedFilterStore
from nsc.tui.app import NscTuiApp

_OBJECT_TYPES = [
    {"app_label": "dcim", "model": "device", "rest_api_endpoint": "/api/dcim/devices/"},
]


def _model() -> CommandModel:
    devices = Resource(
        name="devices",
        list_op=Operation(
            operation_id="dcim_devices_list",
            http_method="GET",
            path="/api/dcim/devices/",
        ),
    )
    return CommandModel(
        info_title="t",
        info_version="1",
        schema_hash="h",
        tags={"dcim": Tag(name="dcim", resources={"devices": devices})},
    )


class _FakeClient:
    def __init__(self, saved: list[dict[str, Any]] | None = None) -> None:
        self._saved = saved or []
        self.posts: list[tuple[str, Any]] = []
        self.deletes: list[str] = []

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        if path == "/api/core/object-types/":
            yield from _OBJECT_TYPES
            return
        if path == SAVED_FILTERS_PATH:
            name = (params or {}).get("name")
            for rec in self._saved:
                if name is None or rec.get("name") == name:
                    yield rec

    def post(self, path: str, *, json: Any = None, **kw: Any) -> dict[str, Any]:
        self.posts.append((path, json))
        return {"id": 1, **(json or {})}

    def delete(self, path: str, **kw: Any) -> dict[str, Any]:
        self.deletes.append(path)
        return {}


def _app(client: _FakeClient, config: Config | None = None) -> NscTuiApp:
    fallback = ConfigFileSavedSearchStore(config or Config(), config_file=None)
    store = NativeSavedFilterStore(client, fallback, on_error=lambda _m: None)
    return NscTuiApp(_model(), client, saved_filter_store=store)


def test_saved_searches_for_reads_native_filters() -> None:
    client = _FakeClient([{"id": 5, "name": "active", "parameters": {"status": ["active"]}}])
    app = _app(client)
    assert app.saved_searches_for("dcim", "devices") == {"active": {"status": "active"}}


def test_save_search_creates_native_filter_with_object_type() -> None:
    client = _FakeClient([])
    app = _app(client)
    app.save_search("dcim", "devices", "active", {"status": "active"})
    assert len(client.posts) == 1
    _path, body = client.posts[0]
    assert body["object_types"] == ["dcim.device"]
    assert body["parameters"] == {"status": ["active"]}


def test_delete_search_removes_native_filter() -> None:
    client = _FakeClient([{"id": 5, "name": "active", "parameters": {}}])
    app = _app(client)
    app.delete_search("dcim", "devices", "active")
    assert client.deletes == [f"{SAVED_FILTERS_PATH}5/"]


def test_app_wires_store_error_notifier() -> None:
    # The app gives the store a way to surface API failures rather than letting
    # them fail silently.
    store = NativeSavedFilterStore(_FakeClient(), ConfigFileSavedSearchStore(Config()))
    app = NscTuiApp(_model(), _FakeClient(), saved_filter_store=store)
    assert store.on_error is not None
    assert app is not None
