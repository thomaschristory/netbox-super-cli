from __future__ import annotations

import io

from nsc.output.table import render as render_table


def test_table_renders_header_and_rows() -> None:
    buf = io.StringIO()
    render_table(
        [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}],
        stream=buf,
        columns=["id", "name"],
    )
    text = buf.getvalue()
    assert "id" in text
    assert "name" in text
    assert "1" in text and "a" in text
    assert "2" in text and "b" in text


def test_table_blank_cell_for_missing_column() -> None:
    buf = io.StringIO()
    render_table([{"id": 1}], stream=buf, columns=["id", "name"])
    text = buf.getvalue()
    assert "id" in text and "name" in text
    assert "1" in text


def test_table_flattens_nested_columns() -> None:
    buf = io.StringIO()
    render_table(
        [{"id": 1, "site": {"name": "DC1"}}],
        stream=buf,
        columns=["id", "site.name"],
    )
    text = buf.getvalue()
    assert "DC1" in text
    assert "site.name" in text


def test_table_renders_single_object_as_one_row() -> None:
    buf = io.StringIO()
    render_table({"id": 1, "name": "x"}, stream=buf, columns=["id", "name"])
    text = buf.getvalue()
    assert "id" in text and "name" in text and "x" in text


def test_table_uses_record_keys_when_no_columns_given() -> None:
    buf = io.StringIO()
    render_table([{"id": 1, "name": "x"}], stream=buf, columns=None)
    text = buf.getvalue()
    assert "id" in text and "name" in text and "x" in text


def test_table_renders_placeholder_for_empty_list() -> None:
    buf = io.StringIO()
    render_table([], stream=buf)
    assert "(no records)" in buf.getvalue()
