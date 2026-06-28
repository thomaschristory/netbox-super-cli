"""Resolve a NetBox list endpoint to its ``app_label.model`` object type.

NetBox identifies a saved filter's target by object type (e.g. ``dcim.device``).
The only robust, version-stable mapping from one of nsc's list resources to that
string is NetBox's own object-type registry: ``/api/core/object-types/`` returns,
for every model, its ``app_label``, ``model``, and ``rest_api_endpoint`` (the
model's list URL). Matching a resource's list path against ``rest_api_endpoint``
avoids fragile depluralization guesses (``ip-addresses`` -> ``ipaddress``) and the
schema-name noise (devices' schema is ``DeviceWithConfigContext``, not ``Device``).
"""

from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import urlsplit

from nsc.http.errors import NetBoxAPIError, NetBoxClientError

_OBJECT_TYPES_PATH = "/api/core/object-types/"


class _ClientLike(Protocol):
    def paginate(
        self, path: str, params: dict[str, Any] | None = ..., *, limit: int | None = ...
    ) -> Any: ...


def normalize_endpoint(path_or_url: str) -> str:
    """A list path/URL reduced to a comparable ``/api/.../`` form.

    Strips any scheme+host and any deployment sub-path prefix, lowercases, and
    ensures a single trailing slash, so a resource's ``Operation.path`` (always a
    bare ``/api/...``) and an object type's server-built ``rest_api_endpoint``
    compare equal regardless of absolute-vs-relative, casing, *or* a NetBox
    sub-path install (where ``rest_api_endpoint`` is e.g. ``/netbox/api/...``).
    """
    path = urlsplit(path_or_url).path.lower()
    marker = "/api/"
    idx = path.find(marker)
    if idx > 0:
        path = path[idx:]
    if not path.endswith("/"):
        path += "/"
    return path


def app_label_from_path(list_path: str) -> str | None:
    """The NetBox app label a list path belongs to, or None if not derivable.

    ``/api/dcim/devices/`` -> ``dcim``; plugin routes
    ``/api/plugins/<plugin>/...`` -> ``<plugin>``.
    """
    parts = [p for p in urlsplit(list_path).path.split("/") if p]
    if not parts or parts[0] != "api" or len(parts) < 2:  # noqa: PLR2004
        return None
    if parts[1] == "plugins":
        return parts[2] if len(parts) >= 3 else None  # noqa: PLR2004
    return parts[1]


def object_type_index(object_types: Any) -> dict[str, str]:
    """Map normalized ``rest_api_endpoint`` -> ``app_label.model`` for each type."""
    index: dict[str, str] = {}
    for ot in object_types:
        endpoint = ot.get("rest_api_endpoint")
        app_label = ot.get("app_label")
        model = ot.get("model")
        if endpoint and app_label and model:
            index[normalize_endpoint(endpoint)] = f"{app_label}.{model}"
    return index


class ObjectTypeResolver:
    """Looks up object types from the live registry, cached per app label."""

    def __init__(self, client: _ClientLike) -> None:
        self._client = client
        self._cache: dict[str, dict[str, str]] = {}

    def resolve(self, list_path: str) -> str | None:
        """``app_label.model`` for a list path, or None if it can't be resolved.

        Returns None (rather than raising) when the path is unparseable or the
        registry can't be reached, so callers can fall back to local storage.
        """
        app_label = app_label_from_path(list_path)
        if app_label is None:
            return None
        index = self._index_for(app_label)
        if index is None:
            return None
        return index.get(normalize_endpoint(list_path))

    def _index_for(self, app_label: str) -> dict[str, str] | None:
        if app_label in self._cache:
            return self._cache[app_label]
        try:
            records = list(self._client.paginate(_OBJECT_TYPES_PATH, {"app_label": app_label}))
        except (NetBoxAPIError, NetBoxClientError):
            return None
        index = object_type_index(records)
        self._cache[app_label] = index
        return index
