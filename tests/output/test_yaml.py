from __future__ import annotations

import io

from ruamel.yaml import YAML

from nsc.output.yaml_ import render as render_yaml


def _safe_load(text: str) -> object:
    return YAML(typ="safe").load(io.StringIO(text))


def test_yaml_block_style_for_list() -> None:
    buf = io.StringIO()
    render_yaml([{"id": 1, "name": "a"}, {"id": 2, "name": "b"}], stream=buf)
    parsed = _safe_load(buf.getvalue())
    assert parsed == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    assert "{" not in buf.getvalue()


def test_yaml_preserves_key_order() -> None:
    buf = io.StringIO()
    render_yaml({"id": 1, "name": "x", "site": "DC1"}, stream=buf)
    text = buf.getvalue()
    assert text.index("id:") < text.index("name:") < text.index("site:")


def test_yaml_output_round_trips_through_ruamel_safe_loader() -> None:
    buf = io.StringIO()
    render_yaml([{"id": 1, "name": "a"}], stream=buf)
    parsed = _safe_load(buf.getvalue())
    assert parsed == [{"id": 1, "name": "a"}]
