"""Pure, Textual-free filter curation, raw parsing, and active-filter state.

A NetBox list endpoint exposes hundreds of query params. ``common_filters``
curates a small, web-UI-like set (search + enum dropdowns + conventional field
names); ``searchable_filters`` exposes the full long tail (including ``__``
lookups) for the builder's search box. Curation is generic — driven by the
schema and naming conventions, never per-model tables.
"""

from __future__ import annotations

from nsc.model.command_model import Operation, Parameter, ParameterLocation

_DROP_EXACT = frozenset({"limit", "offset", "start", "ordering", "brief", "fields", "omit"})

# Model-agnostic NetBox field-name conventions, in display order. Matched only
# when actually present on the operation — no hard-coded per-model wiring.
_ALLOWLIST: tuple[str, ...] = (
    "name",
    "slug",
    "label",
    "description",
    "status",
    "role",
    "tag",
    "tenant",
    "site",
    "device",
    "region",
    "group",
    "platform",
    "manufacturer",
    "vrf",
    "vlan",
    "address",
    "dns_name",
    "serial",
    "asset_tag",
    "mac_address",
)

_COMMON_CAP = 20


def _dropped(name: str) -> bool:
    return name in _DROP_EXACT or name.endswith("_count") or name.endswith("_by_request")


def _query_params(operation: Operation) -> list[Parameter]:
    return [p for p in operation.parameters if p.location is ParameterLocation.QUERY]


def common_filters(operation: Operation) -> list[Parameter]:
    by_name = {p.name: p for p in _query_params(operation)}
    chosen: list[Parameter] = []
    seen: set[str] = set()

    def take(param: Parameter) -> None:
        chosen.append(param)
        seen.add(param.name)

    if "q" in by_name:
        take(by_name["q"])
    for param in _query_params(operation):
        if (
            param.name not in seen
            and "__" not in param.name
            and param.enum is not None
            and not _dropped(param.name)
        ):
            take(param)
    for name in _ALLOWLIST:
        candidate = by_name.get(name)
        if candidate is not None and name not in seen and not _dropped(name):
            take(candidate)
    # Spec: when both `x` and `x_id` are chosen, COMMON shows `x`; the `x_id`
    # form stays reachable via search. Make that contract explicit, not
    # incidental to which names happen to be in the allowlist.
    chosen = [p for p in chosen if not (p.name.endswith("_id") and p.name[: -len("_id")] in seen)]
    return chosen[:_COMMON_CAP]


def searchable_filters(operation: Operation) -> list[Parameter]:
    params = [p for p in _query_params(operation) if not _dropped(p.name)]
    return sorted(params, key=lambda p: p.name)


def parse_raw(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in text.split():
        if "=" in token:
            key, _, value = token.partition("=")
            key = key.strip()
            value = value.strip()
            # Skip empty values so a `name=` token (e.g. from the search->raw
            # affordance, submitted without a value) is a no-op, not a clear.
            # Clearing stays the job of chip removal / Clear.
            if key and value:
                out[key] = value
    return out


class FilterState:
    """Ordered, mutable map of active ``key -> value`` filters."""

    def __init__(self) -> None:
        self._items: dict[str, str] = {}

    @classmethod
    def from_params(cls, params: dict[str, str]) -> FilterState:
        state = cls()
        for key, value in params.items():
            state.set(key, value)
        return state

    def set(self, key: str, value: str) -> None:
        if value == "":
            self._items.pop(key, None)
            return
        self._items[key] = value

    def remove(self, key: str) -> None:
        self._items.pop(key, None)

    def merge(self, params: dict[str, str]) -> None:
        for key, value in params.items():
            self.set(key, value)

    def as_params(self) -> dict[str, str]:
        return dict(self._items)
