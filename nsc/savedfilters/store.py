"""A saved-search store backed by NetBox ``extras.saved-filters`` objects.

Primary storage is the server, so a search saved here appears in the NetBox web
UI (and vice versa). Every operation degrades to a local fallback (config.yaml)
when the object type can't be resolved or the API is unreachable, and surfaces
that degradation through an optional ``on_error`` callback rather than failing
silently.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from nsc.http.errors import NetBoxAPIError, NetBoxClientError
from nsc.savedfilters.objecttypes import ObjectTypeResolver
from nsc.savedfilters.params import (
    from_netbox_parameters,
    slugify,
    to_netbox_parameters,
)

SAVED_FILTERS_PATH = "/api/extras/saved-filters/"


class SavedSearchFallback(Protocol):
    """Local, offline storage keyed by ``(tag, resource)`` — the config.yaml map."""

    def list(self, tag: str, resource: str) -> dict[str, dict[str, str]]: ...
    def save(self, tag: str, resource: str, name: str, params: dict[str, str]) -> None: ...
    def delete(self, tag: str, resource: str, name: str) -> None: ...


class _ResolverLike(Protocol):
    def resolve(self, list_path: str) -> str | None: ...


class NativeSavedFilterStore:
    def __init__(
        self,
        client: Any,
        fallback: SavedSearchFallback,
        *,
        resolver: _ResolverLike | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._client = client
        self._fallback = fallback
        self._resolver = resolver or ObjectTypeResolver(client)
        self.on_error = on_error

    def list(self, list_path: str, tag: str, resource: str) -> dict[str, dict[str, str]]:
        object_type = self._resolver.resolve(list_path)
        if object_type is None:
            return self._fallback.list(tag, resource)
        try:
            records = self._client.paginate(SAVED_FILTERS_PATH, {"object_type": object_type})
            out: dict[str, dict[str, str]] = {}
            for rec in records:
                name = rec.get("name")
                if not name:
                    continue
                if name in out:
                    # NetBox allows same-named filters (e.g. a per-user one and a
                    # shared one). Keep the first deterministically — matching
                    # _find's save/delete target — and flag the ambiguity.
                    self._notify(f"Multiple NetBox saved filters named {name!r}; using the first.")
                    continue
                out[name] = from_netbox_parameters(rec.get("parameters") or {})
            return out
        except (NetBoxAPIError, NetBoxClientError) as exc:
            self._report("load saved searches", exc)
            return self._fallback.list(tag, resource)

    def save(
        self, list_path: str, tag: str, resource: str, name: str, params: dict[str, str]
    ) -> None:
        object_type = self._resolver.resolve(list_path)
        if object_type is None:
            self._fallback.save(tag, resource, name, params)
            return
        try:
            existing = self._find(object_type, name)
            parameters = to_netbox_parameters(params)
            if existing is None:
                self._client.post(
                    SAVED_FILTERS_PATH,
                    json={
                        "name": name,
                        "slug": slugify(f"{object_type}-{name}"),
                        "object_types": [object_type],
                        "parameters": parameters,
                        "enabled": True,
                        "shared": True,
                    },
                    operation_id="extras_saved_filters_create",
                )
            else:
                # Update parameters only; leaving name/slug intact preserves a
                # slug NetBox (or the web UI) already assigned to this filter.
                self._client.patch(
                    f"{SAVED_FILTERS_PATH}{existing['id']}/",
                    json={"object_types": [object_type], "parameters": parameters},
                    operation_id="extras_saved_filters_partial_update",
                )
        except (NetBoxAPIError, NetBoxClientError) as exc:
            self._report(f"save search {name!r}", exc)
            self._fallback.save(tag, resource, name, params)

    def delete(self, list_path: str, tag: str, resource: str, name: str) -> None:
        object_type = self._resolver.resolve(list_path)
        if object_type is None:
            self._fallback.delete(tag, resource, name)
            return
        try:
            existing = self._find(object_type, name)
            if existing is not None:
                self._client.delete(
                    f"{SAVED_FILTERS_PATH}{existing['id']}/",
                    operation_id="extras_saved_filters_destroy",
                )
        except (NetBoxAPIError, NetBoxClientError) as exc:
            self._report(f"delete search {name!r}", exc)
            self._fallback.delete(tag, resource, name)

    def _find(self, object_type: str, name: str) -> dict[str, Any] | None:
        records = self._client.paginate(
            SAVED_FILTERS_PATH, {"object_type": object_type, "name": name}
        )
        for rec in records:
            if rec.get("name") == name:
                return cast(dict[str, Any], rec)
        return None

    def _report(self, action: str, exc: Exception) -> None:
        self._notify(f"Could not {action} via NetBox ({exc}); using local config.")

    def _notify(self, message: str) -> None:
        if self.on_error is not None:
            self.on_error(message)
