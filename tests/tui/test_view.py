from __future__ import annotations

from rich.text import Text

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


def test_build_rows_without_object_colors_returns_plain_str() -> None:
    records = [{"role": {"display": "Router", "color": "4caf50"}}]
    rows = build_rows(records, ["role"])
    assert rows == [["Router"]]


def test_build_rows_object_colors_produces_styled_text() -> None:
    records = [{"role": {"display": "Router", "color": "4caf50"}}]
    rows = build_rows(records, ["role"], object_colors=True)
    cell = rows[0][0]
    assert isinstance(cell, Text)
    assert cell.plain == "Router"
    assert str(cell.style) == "#4caf50"


def test_build_rows_object_colors_list_of_tags_joins_styled_text() -> None:
    records = [
        {
            "tags": [
                {"display": "prod", "color": "ff0000"},
                {"display": "edge", "color": "00ff00"},
            ]
        }
    ]
    rows = build_rows(records, ["tags"], object_colors=True)
    cell = rows[0][0]
    assert isinstance(cell, Text)
    assert cell.plain == "prod, edge"
    styles = {str(span.style) for span in cell.spans}
    assert "#ff0000" in styles
    assert "#00ff00" in styles


def test_build_rows_object_colors_mixed_tag_list_joins_cleanly() -> None:
    # One tag colored, one without — the row must be a single styled Text with
    # both labels joined, not a fall-through to str(value) with a raw repr.
    records = [
        {
            "tags": [
                {"display": "prod", "color": "ff0000"},
                {"display": "edge"},
            ]
        }
    ]
    rows = build_rows(records, ["tags"], object_colors=True)
    cell = rows[0][0]
    assert isinstance(cell, Text)
    assert cell.plain == "prod, edge"
    styles = {str(span.style) for span in cell.spans}
    assert "#ff0000" in styles


def test_build_rows_object_colors_object_without_color_is_plain_str() -> None:
    records = [{"role": {"display": "Router"}}]
    rows = build_rows(records, ["role"], object_colors=True)
    assert rows == [["Router"]]
