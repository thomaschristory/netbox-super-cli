from __future__ import annotations

from nsc.model.command_model import Operation
from nsc.tui.view import build_rows, choose_columns


def _op(default_columns: list[str] | None) -> Operation:
    return Operation(
        operation_id="x_list",
        http_method="GET",
        path="/api/x/",
        default_columns=default_columns,
    )


def test_choose_columns_prefers_configured_then_default_then_sample() -> None:
    op = _op(["id", "name"])
    assert choose_columns(op, ["name", "status"], {"id": 1}) == ["name", "status"]
    assert choose_columns(op, None, {"id": 1}) == ["id", "name"]
    assert choose_columns(_op(None), None, {"id": 1, "name": "a"}) == ["id", "name"]
    assert choose_columns(_op(None), None, None) == ["id"]


def test_build_rows_flattens_to_selected_columns_as_strings() -> None:
    records = [{"id": 1, "site": {"display": "HQ"}}, {"id": 2, "site": None}]
    rows = build_rows(records, ["id", "site.display"])
    assert rows == [["1", "HQ"], ["2", ""]]
