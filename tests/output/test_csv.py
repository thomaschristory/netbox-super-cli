from __future__ import annotations

import csv
import io

from nsc.output.csv_ import render as render_csv


def test_csv_writes_header_and_rows_for_list_of_records() -> None:
    buf = io.StringIO()
    render_csv(
        [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}],
        stream=buf,
        columns=["id", "name"],
    )
    rows = list(csv.reader(io.StringIO(buf.getvalue())))
    assert rows[0] == ["id", "name"]
    assert rows[1] == ["1", "a"]
    assert rows[2] == ["2", "b"]


def test_csv_flattens_nested_fields_with_dotted_paths() -> None:
    buf = io.StringIO()
    render_csv(
        [{"id": 1, "site": {"name": "DC1"}}],
        stream=buf,
        columns=["id", "site.name"],
    )
    rows = list(csv.reader(io.StringIO(buf.getvalue())))
    assert rows[0] == ["id", "site.name"]
    assert rows[1] == ["1", "DC1"]


def test_csv_blank_for_missing_columns() -> None:
    buf = io.StringIO()
    render_csv([{"id": 1}], stream=buf, columns=["id", "name"])
    rows = list(csv.reader(io.StringIO(buf.getvalue())))
    assert rows[1] == ["1", ""]


def test_csv_renders_single_object_as_one_row() -> None:
    buf = io.StringIO()
    render_csv({"id": 1, "name": "x"}, stream=buf, columns=["id", "name"])
    rows = list(csv.reader(io.StringIO(buf.getvalue())))
    assert rows == [["id", "name"], ["1", "x"]]


def test_csv_uses_record_keys_when_no_columns_given() -> None:
    buf = io.StringIO()
    render_csv([{"id": 1, "name": "a"}], stream=buf, columns=None)
    rows = list(csv.reader(io.StringIO(buf.getvalue())))
    assert set(rows[0]) == {"id", "name"}
