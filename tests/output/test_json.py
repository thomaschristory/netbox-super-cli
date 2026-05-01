from __future__ import annotations

import io
import json

from nsc.output.json_ import render as render_json


def test_json_renders_list() -> None:
    buf = io.StringIO()
    render_json([{"id": 1}, {"id": 2}], stream=buf, compact=False)
    assert json.loads(buf.getvalue()) == [{"id": 1}, {"id": 2}]


def test_json_renders_single_object_without_array_wrap() -> None:
    buf = io.StringIO()
    render_json({"id": 1}, stream=buf, compact=False)
    assert json.loads(buf.getvalue()) == {"id": 1}


def test_json_compact_is_one_line() -> None:
    buf = io.StringIO()
    render_json([{"id": 1}, {"id": 2}], stream=buf, compact=True)
    text = buf.getvalue().rstrip("\n")
    assert "\n" not in text
