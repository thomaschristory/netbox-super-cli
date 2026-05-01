from __future__ import annotations

import io

import yaml

from nsc.output.yaml_ import render as render_yaml


def test_yaml_block_style_for_list() -> None:
    buf = io.StringIO()
    render_yaml([{"id": 1, "name": "a"}, {"id": 2, "name": "b"}], stream=buf)
    parsed = yaml.safe_load(buf.getvalue())
    assert parsed == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    assert "{" not in buf.getvalue()


def test_yaml_preserves_key_order() -> None:
    buf = io.StringIO()
    render_yaml({"id": 1, "name": "x", "site": "DC1"}, stream=buf)
    text = buf.getvalue()
    assert text.index("id:") < text.index("name:") < text.index("site:")
