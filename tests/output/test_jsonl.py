from __future__ import annotations

import io
import json

from nsc.output.jsonl import render as render_jsonl


def test_jsonl_one_record_per_line() -> None:
    buf = io.StringIO()
    render_jsonl([{"id": 1}, {"id": 2}], stream=buf)
    lines = [line for line in buf.getvalue().splitlines() if line]
    assert [json.loads(line) for line in lines] == [{"id": 1}, {"id": 2}]


def test_jsonl_single_object_emits_one_line() -> None:
    buf = io.StringIO()
    render_jsonl({"id": 1}, stream=buf)
    lines = [line for line in buf.getvalue().splitlines() if line]
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"id": 1}
