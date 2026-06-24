from __future__ import annotations

from typing import Any

from nsc.model.command_model import (
    CommandModel,
    Operation,
    Parameter,
    ParameterLocation,
    Resource,
    Tag,
)
from nsc.tui.catalog import ResourceRef
from nsc.tui.search import global_search_targets, search_target


def _list_op(path: str, *, with_q: bool) -> Operation:
    params = [Parameter(name="q", location=ParameterLocation.QUERY)] if with_q else []
    return Operation(operation_id=path, http_method="GET", path=path, parameters=params)


def _model() -> CommandModel:
    dcim = Tag(
        name="dcim",
        resources={
            "devices": Resource(
                name="devices", list_op=_list_op("/api/dcim/devices/", with_q=True)
            ),
            # present but NOT q-capable -> must be skipped
            "cables": Resource(name="cables", list_op=_list_op("/api/dcim/cables/", with_q=False)),
        },
    )
    ipam = Tag(
        name="ipam",
        resources={
            "prefixes": Resource(
                name="prefixes", list_op=_list_op("/api/ipam/prefixes/", with_q=True)
            ),
        },
    )
    return CommandModel(
        info_title="t", info_version="1", schema_hash="h", tags={"dcim": dcim, "ipam": ipam}
    )


def test_global_search_targets_keeps_allowlist_order_present_and_q_capable() -> None:
    targets = global_search_targets(_model())
    # devices before prefixes (allowlist order); cables dropped (no q); absent
    # allowlist names simply do not appear.
    assert [t.resource_name for t in targets] == ["devices", "prefixes"]


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None, int | None]] = []

    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any:
        self.calls.append((path, params, limit))
        yield {"id": 1, "display": "sw1"}


def test_search_target_queries_with_q_and_limit() -> None:
    client = _RecordingClient()
    ref = ResourceRef("dcim", "devices", _list_op("/api/dcim/devices/", with_q=True))
    rows = search_target(client, ref, "sw", limit=5)
    assert rows == [{"id": 1, "display": "sw1"}]
    assert client.calls == [("/api/dcim/devices/", {"q": "sw"}, 5)]
