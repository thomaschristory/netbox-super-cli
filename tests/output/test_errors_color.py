from __future__ import annotations

import io
import re

from nsc.output.errors import ErrorEnvelope, ErrorType, render_to_rich_stderr


def strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def _envelope() -> ErrorEnvelope:
    return ErrorEnvelope(error="not found", type=ErrorType.NOT_FOUND)


def test_render_to_rich_stderr_color_false_no_ansi() -> None:
    buf = io.StringIO()
    render_to_rich_stderr(_envelope(), stream=buf, color=False)
    assert "\x1b[" not in buf.getvalue()
    assert "not found" in buf.getvalue()


def test_render_to_rich_stderr_color_true_has_ansi() -> None:
    buf = io.StringIO()
    render_to_rich_stderr(_envelope(), stream=buf, color=True)
    out = buf.getvalue()
    assert "\x1b[" in out
    assert "not found" in strip_ansi(out)


def test_render_to_rich_stderr_escapes_markup_in_api_values() -> None:
    """Server-sourced error/endpoint/details text containing [..] must not be
    parsed as Rich markup (would garble output or raise MarkupError)."""
    env = ErrorEnvelope(
        error="invalid value [foo]",
        type=ErrorType.VALIDATION,
        endpoint="/api/dcim/devices/[bad]/",
        details={"hint": "remove the [brackets]"},
    )
    for color in (True, False):
        buf = io.StringIO()
        render_to_rich_stderr(env, stream=buf, color=color)
        out = strip_ansi(buf.getvalue())
        assert "[foo]" in out
        assert "[bad]" in out
        assert "[brackets]" in out
