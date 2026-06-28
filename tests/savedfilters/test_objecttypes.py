from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from nsc.http.errors import NetBoxAPIError
from nsc.savedfilters.objecttypes import (
    ObjectTypeResolver,
    app_label_from_path,
    normalize_endpoint,
    object_type_index,
)

_OBJECT_TYPES = [
    {"app_label": "dcim", "model": "device", "rest_api_endpoint": "/api/dcim/devices/"},
    {"app_label": "dcim", "model": "devicetype", "rest_api_endpoint": "/api/dcim/device-types/"},
    {"app_label": "ipam", "model": "ipaddress", "rest_api_endpoint": "/api/ipam/ip-addresses/"},
]


def test_normalize_endpoint_handles_full_urls_and_trailing_slash() -> None:
    assert normalize_endpoint("https://nb.example.com/api/dcim/devices/") == "/api/dcim/devices/"
    assert normalize_endpoint("/api/dcim/devices") == "/api/dcim/devices/"
    assert normalize_endpoint("/API/DCIM/Devices/") == "/api/dcim/devices/"


def test_normalize_endpoint_strips_deployment_subpath_prefix() -> None:
    # NetBox installed under a sub-path returns rest_api_endpoint with the prefix;
    # Operation.path never has it, so both must reduce to the same /api/... tail.
    assert normalize_endpoint("/netbox/api/dcim/devices/") == "/api/dcim/devices/"
    assert (
        normalize_endpoint("https://nb.example.com/netbox/api/dcim/devices/")
        == "/api/dcim/devices/"
    )


def test_resolver_matches_across_subpath_casing_and_trailing_slash() -> None:
    # End-to-end: a sub-path, absolute-URL, mixed-case rest_api_endpoint still
    # resolves the bare lowercase Operation.path that nsc passes in.
    client = _FakeClient(
        [
            {
                "app_label": "dcim",
                "model": "device",
                "rest_api_endpoint": "https://nb.example.com/NetBox/API/DCIM/Devices/",
            }
        ]
    )
    resolver = ObjectTypeResolver(client)
    assert resolver.resolve("/api/dcim/devices/") == "dcim.device"


def test_app_label_from_path() -> None:
    assert app_label_from_path("/api/dcim/devices/") == "dcim"
    assert app_label_from_path("/api/ipam/ip-addresses/") == "ipam"
    assert app_label_from_path("/api/plugins/myplugin/widgets/") == "myplugin"
    assert app_label_from_path("/notapi/") is None


def test_object_type_index_maps_endpoint_to_dotted_type() -> None:
    index = object_type_index(_OBJECT_TYPES)
    assert index["/api/dcim/devices/"] == "dcim.device"
    assert index["/api/ipam/ip-addresses/"] == "ipam.ipaddress"


class _FakeClient:
    def __init__(self, records: list[dict[str, Any]], *, fail: bool = False) -> None:
        self._records = records
        self._fail = fail
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        self.calls.append((path, params))
        if self._fail:
            raise NetBoxAPIError(status_code=404, url=path, body_snippet="", headers={})
        app = (params or {}).get("app_label")
        for rec in self._records:
            if app is None or rec["app_label"] == app:
                yield rec


def test_resolver_returns_dotted_object_type_for_a_list_path() -> None:
    client = _FakeClient(_OBJECT_TYPES)
    resolver = ObjectTypeResolver(client)
    assert resolver.resolve("/api/ipam/ip-addresses/") == "ipam.ipaddress"


def test_resolver_filters_object_types_by_app_label() -> None:
    client = _FakeClient(_OBJECT_TYPES)
    resolver = ObjectTypeResolver(client)
    resolver.resolve("/api/dcim/devices/")
    assert client.calls == [("/api/core/object-types/", {"app_label": "dcim"})]


def test_resolver_caches_per_app_label() -> None:
    client = _FakeClient(_OBJECT_TYPES)
    resolver = ObjectTypeResolver(client)
    resolver.resolve("/api/dcim/devices/")
    resolver.resolve("/api/dcim/device-types/")
    assert len(client.calls) == 1


def test_resolver_returns_none_on_api_error() -> None:
    client = _FakeClient(_OBJECT_TYPES, fail=True)
    resolver = ObjectTypeResolver(client)
    assert resolver.resolve("/api/dcim/devices/") is None


def test_resolver_returns_none_for_unknown_endpoint() -> None:
    client = _FakeClient(_OBJECT_TYPES)
    resolver = ObjectTypeResolver(client)
    assert resolver.resolve("/api/dcim/nonexistent/") is None


@pytest.mark.parametrize("bad_path", ["", "/", "notapath"])
def test_resolver_returns_none_for_unparseable_path(bad_path: str) -> None:
    client = _FakeClient(_OBJECT_TYPES)
    resolver = ObjectTypeResolver(client)
    assert resolver.resolve(bad_path) is None
