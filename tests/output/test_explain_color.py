from __future__ import annotations

import io
import re

from nsc.output.explain import ExplainTrace, render_to_rich_stdout


def strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def _trace() -> ExplainTrace:
    return ExplainTrace(
        operation_id="dcim_devices_create",
        method_reasoning="POST per OpenAPI operation 'dcim_devices_create'",
        url_reasoning="No path templating",
    )


def test_render_to_rich_stdout_color_false_no_ansi() -> None:
    buf = io.StringIO()
    render_to_rich_stdout(_trace(), stream=buf, color=False)
    out = buf.getvalue()
    assert "\x1b[" not in out
    assert "dcim_devices_create" in out


def test_render_to_rich_stdout_color_true_has_ansi() -> None:
    buf = io.StringIO()
    render_to_rich_stdout(_trace(), stream=buf, color=True)
    out = buf.getvalue()
    assert "\x1b[" in out
    assert "dcim_devices_create" in strip_ansi(out)


def test_render_to_rich_stdout_escapes_markup() -> None:
    """Reasoning strings carry user/schema values that may contain [..];
    they must render literally, not as Rich markup."""
    trace = ExplainTrace(
        operation_id="dcim_devices_create",
        method_reasoning="POST [special]",
        url_reasoning="path template '/api/x/[v2]/'",
    )
    for color in (True, False):
        buf = io.StringIO()
        render_to_rich_stdout(trace, stream=buf, color=color)
        out = strip_ansi(buf.getvalue())
        assert "[special]" in out
        assert "[v2]" in out
