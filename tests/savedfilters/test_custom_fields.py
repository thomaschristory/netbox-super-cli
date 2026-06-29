from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from nsc.http.errors import NetBoxAPIError
from nsc.savedfilters.custom_fields import (
    CustomFieldDef,
    CustomFieldResolver,
    custom_field_labels,
    humanize,
)

_OBJECT_TYPES = [
    {"app_label": "dcim", "model": "device", "rest_api_endpoint": "/api/dcim/devices/"},
]

_CUSTOM_FIELDS = [
    {
        "name": "site_contact",
        "label": "Site Contact",
        "type": {"value": "text", "label": "Text"},
        "required": False,
    },
    {
        # blank label -> humanized fallback
        "name": "rack_role",
        "label": "",
        "type": {"value": "text", "label": "Text"},
    },
    {
        "name": "tier",
        "label": "Tier",
        "type": {"value": "select", "label": "Selection"},
        "choice_set": {"id": 7, "url": "/api/extras/custom-field-choice-sets/7/"},
    },
]

_CHOICE_SETS = {
    7: {"id": 7, "extra_choices": [["gold", "Gold"], ["silver", "Silver"]]},
}


class _FakeClient:
    def __init__(
        self,
        object_types: list[dict[str, Any]],
        custom_fields: list[dict[str, Any]],
        *,
        fail: bool = False,
    ) -> None:
        self._object_types = object_types
        self._custom_fields = custom_fields
        self._fail = fail
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.gets: list[str] = []

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        self.calls.append((path, params))
        if self._fail:
            raise NetBoxAPIError(status_code=404, url=path, body_snippet="", headers={})
        if path == "/api/core/object-types/":
            app = (params or {}).get("app_label")
            for rec in self._object_types:
                if app is None or rec["app_label"] == app:
                    yield rec
            return
        if path == "/api/extras/custom-fields/":
            yield from self._custom_fields
            return

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.gets.append(path)
        cs_id = int(path.rstrip("/").rsplit("/", 1)[-1])
        return _CHOICE_SETS[cs_id]


def _resolver(**kw: Any) -> CustomFieldResolver:
    client = _FakeClient(_OBJECT_TYPES, _CUSTOM_FIELDS, **kw)
    return CustomFieldResolver(client)


def test_humanize() -> None:
    assert humanize("site_contact") == "Site Contact"
    assert humanize("tier") == "Tier"


def test_resolve_maps_name_to_label_and_type() -> None:
    defs = _resolver().resolve("/api/dcim/devices/")
    assert defs is not None
    assert defs["site_contact"].label == "Site Contact"
    assert defs["site_contact"].type == "text"


def test_resolve_humanizes_blank_label() -> None:
    defs = _resolver().resolve("/api/dcim/devices/")
    assert defs is not None
    assert defs["rack_role"].label == "Rack Role"


def test_resolve_populates_choices_from_choice_set() -> None:
    defs = _resolver().resolve("/api/dcim/devices/")
    assert defs is not None
    assert defs["tier"].type == "select"
    assert defs["tier"].choices == ("gold", "silver")


def test_resolve_caches_per_object_type() -> None:
    client = _FakeClient(_OBJECT_TYPES, _CUSTOM_FIELDS)
    resolver = CustomFieldResolver(client)
    resolver.resolve("/api/dcim/devices/")
    resolver.resolve("/api/dcim/devices/")
    cf_calls = [c for c in client.calls if c[0] == "/api/extras/custom-fields/"]
    assert len(cf_calls) == 1


def test_resolve_scopes_by_object_type() -> None:
    client = _FakeClient(_OBJECT_TYPES, _CUSTOM_FIELDS)
    CustomFieldResolver(client).resolve("/api/dcim/devices/")
    assert ("/api/extras/custom-fields/", {"object_type": "dcim.device"}) in client.calls


def test_resolve_none_on_api_error() -> None:
    assert _resolver(fail=True).resolve("/api/dcim/devices/") is None


def test_resolve_none_when_object_type_unresolvable() -> None:
    client = _FakeClient([], _CUSTOM_FIELDS)
    assert CustomFieldResolver(client).resolve("/api/dcim/devices/") is None


def test_custom_field_labels_maps_keys_and_passes_through_others() -> None:
    defs = {"site_contact": CustomFieldDef(name="site_contact", label="Site Contact")}
    labels = custom_field_labels(["name", "custom_fields.site_contact"], defs)
    assert labels == {"name": "name", "custom_fields.site_contact": "Site Contact"}


def test_custom_field_labels_falls_back_to_raw_on_collision() -> None:
    defs = {
        "a": CustomFieldDef(name="a", label="Dup"),
        "b": CustomFieldDef(name="b", label="Dup"),
    }
    labels = custom_field_labels(["custom_fields.a", "custom_fields.b"], defs)
    assert labels == {"custom_fields.a": "custom_fields.a", "custom_fields.b": "custom_fields.b"}


def test_custom_field_labels_identity_when_defs_none() -> None:
    cols = ["name", "custom_fields.site_contact"]
    assert custom_field_labels(cols, None) == {c: c for c in cols}


def test_custom_field_labels_unknown_cf_falls_back_to_raw() -> None:
    defs: dict[str, CustomFieldDef] = {}
    labels = custom_field_labels(["custom_fields.ghost"], defs)
    assert labels == {"custom_fields.ghost": "custom_fields.ghost"}
