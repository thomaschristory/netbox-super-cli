"""Global-search targets and per-target querying.

NetBox has no global-search REST endpoint, so we approximate the web UI by
fanning out ``?q=<term>`` to a curated set of common, ``q``-capable resource
list endpoints. Curation is a model-agnostic name allowlist intersected with
the live schema; dropping the allowlist would search every ``q``-capable
endpoint (heavier — see the design doc).
"""

from __future__ import annotations

from typing import Any, Protocol

from nsc.model.command_model import CommandModel, ParameterLocation
from nsc.tui.catalog import ResourceRef

# Common object types people search for, in display order. Matched only when
# present in the schema and ``q``-capable, so non-NetBox schemas degrade safely.
GLOBAL_SEARCH_TYPES: tuple[str, ...] = (
    "devices",
    "virtual-machines",
    "ip-addresses",
    "prefixes",
    "ip-ranges",
    "aggregates",
    "sites",
    "locations",
    "racks",
    "interfaces",
    "cables",
    "vlans",
    "vrfs",
    "tenants",
    "circuits",
    "providers",
    "clusters",
)


class _Client(Protocol):
    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any: ...


def _supports_q(operation: Any) -> bool:
    return any(
        p.name == "q" and p.location is ParameterLocation.QUERY for p in operation.parameters
    )


def global_search_targets(model: CommandModel) -> list[ResourceRef]:
    by_name: dict[str, ResourceRef] = {}
    for tag_name, tag in model.tags.items():
        for resource_name, resource in tag.resources.items():
            op = resource.list_op
            if op is not None and _supports_q(op) and resource_name not in by_name:
                by_name[resource_name] = ResourceRef(tag_name, resource_name, op)
    return [by_name[name] for name in GLOBAL_SEARCH_TYPES if name in by_name]


def search_target(
    client: _Client, ref: ResourceRef, term: str, limit: int = 8
) -> list[dict[str, Any]]:
    return list(client.paginate(ref.list_op.path, {"q": term}, limit=limit))
