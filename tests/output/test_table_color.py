from __future__ import annotations

import io
import re

from nsc.output.table import _format_cell, render


def strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


# --- _format_cell ---


def test_format_cell_plain_no_color() -> None:
    assert _format_cell("active", color=False) == "active"
    assert _format_cell("failed", color=False) == "failed"
    assert _format_cell(None, color=False) == ""
    assert _format_cell(True, color=False) == "true"
    assert _format_cell(False, color=False) == "false"


def test_format_cell_status_green_values() -> None:
    for val in ("active", "enabled", "online", "connected", "Active", "ACTIVE"):
        result = _format_cell(val, color=True)
        assert "green" in result, f"expected green for {val!r}, got {result!r}"
        assert val.lower() in result.lower()


def test_format_cell_status_yellow_values() -> None:
    for val in ("planned", "staged", "decommissioning"):
        result = _format_cell(val, color=True)
        assert "yellow" in result


def test_format_cell_status_red_values() -> None:
    for val in ("failed", "disabled", "offline", "error"):
        result = _format_cell(val, color=True)
        assert "red" in result


def test_format_cell_bool_true_green() -> None:
    result = _format_cell(True, color=True)
    assert "green" in result
    assert "true" in result


def test_format_cell_bool_false_dim() -> None:
    result = _format_cell(False, color=True)
    assert "dim" in result
    assert "false" in result


def test_format_cell_empty_dim() -> None:
    result = _format_cell(None, color=True)
    assert "dim" in result


def test_format_cell_unknown_value_no_markup() -> None:
    result = _format_cell("some-hostname", color=True)
    assert result == "some-hostname"


# --- render ---


def test_render_no_color_plain_output() -> None:
    buf = io.StringIO()
    render([{"status": "active", "name": "sw1"}], stream=buf, color=False)
    out = buf.getvalue()
    assert "active" in out
    assert "sw1" in out
    # No ANSI escape sequences
    assert "\x1b[" not in out


def test_render_color_contains_ansi() -> None:
    buf = io.StringIO()
    render([{"status": "active", "name": "sw1"}], stream=buf, color=True)
    out = buf.getvalue()
    # ANSI codes present
    assert "\x1b[" in out
    # Text still present when stripped
    plain = strip_ansi(out)
    assert "active" in plain
    assert "sw1" in plain


def test_render_empty_no_records_message() -> None:
    buf = io.StringIO()
    render([], stream=buf, color=False)
    assert "no records" in buf.getvalue()
