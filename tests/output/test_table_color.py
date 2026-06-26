from __future__ import annotations

import io
import re

from nsc.config.models import OutputFormat
from nsc.output.colors import ColoredValue
from nsc.output.render import render as render_dispatch
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


def test_render_color_escapes_markup_in_values() -> None:
    """A cell value containing valid Rich tags must render literally, not be
    consumed as markup."""
    buf = io.StringIO()
    render([{"name": "host [dim]x[/dim]"}], stream=buf, color=True)
    out = strip_ansi(buf.getvalue())
    assert "[dim]" in out


def test_render_no_color_escapes_markup_in_values() -> None:
    buf = io.StringIO()
    render([{"name": "host [dim]x[/dim]"}], stream=buf, color=False)
    out = buf.getvalue()
    assert "[dim]" in out


# --- render_dispatch (the main entry point) ---


def test_render_dispatch_passes_color_to_table() -> None:
    buf = io.StringIO()
    render_dispatch(
        [{"status": "active"}],
        format=OutputFormat.TABLE,
        stream=buf,
        color=True,
    )
    assert "\x1b[" in buf.getvalue()


def test_render_dispatch_non_table_ignores_color() -> None:
    buf = io.StringIO()
    render_dispatch(
        [{"status": "active"}],
        format=OutputFormat.JSON,
        stream=buf,
        color=True,
    )
    out = buf.getvalue()
    assert "\x1b[" not in out
    assert "active" in out


# --- object colors ---


def test_format_cell_colored_value_emits_hex_markup() -> None:
    result = _format_cell(ColoredValue("Router", "4caf50"), color=True)
    assert "#4caf50" in result
    assert "Router" in result


def test_format_cell_colored_value_escapes_markup_in_text() -> None:
    result = _format_cell(ColoredValue("ro[le]", "4caf50"), color=True)
    assert "#4caf50" in result
    assert "\\[le]" in result


def test_format_cell_colored_value_no_color_strips_markup_but_escapes() -> None:
    result = _format_cell(ColoredValue("ro[le]", "4caf50"), color=False)
    assert "#4caf50" not in result
    assert "\\[le]" in result


def test_format_cell_colored_value_list_comma_joined_colored() -> None:
    result = _format_cell(
        [ColoredValue("prod", "ff0000"), ColoredValue("edge", "00ff00")], color=True
    )
    assert "#ff0000" in result
    assert "#00ff00" in result
    assert "prod" in result
    assert "edge" in result


def test_render_object_colors_emits_role_hex() -> None:
    buf = io.StringIO()
    render(
        [{"role": {"display": "Router", "color": "4caf50"}}],
        stream=buf,
        columns=["role"],
        color=True,
        object_colors=True,
    )
    out = buf.getvalue()
    assert "\x1b[" in out
    assert "Router" in strip_ansi(out)


def test_render_object_colors_off_keeps_status_colors_on() -> None:
    buf = io.StringIO()
    render(
        [{"status": "active", "role": {"display": "Router", "color": "4caf50"}}],
        stream=buf,
        columns=["status", "role"],
        color=True,
        object_colors=False,
    )
    out = buf.getvalue()
    # status still colored (ANSI present), role rendered as plain text
    assert "\x1b[" in out
    plain = strip_ansi(out)
    assert "active" in plain
    assert "Router" in plain


def test_render_object_colors_requires_color() -> None:
    buf = io.StringIO()
    render(
        [{"role": {"display": "Router [x]", "color": "4caf50"}}],
        stream=buf,
        columns=["role"],
        color=False,
        object_colors=True,
    )
    out = buf.getvalue()
    assert "\x1b[" not in out
    assert "[x]" in out


def test_render_dispatch_forwards_object_colors() -> None:
    buf = io.StringIO()
    render_dispatch(
        [{"role": {"display": "Router", "color": "4caf50"}}],
        format=OutputFormat.TABLE,
        columns=["role"],
        stream=buf,
        color=True,
        object_colors=True,
    )
    assert "\x1b[" in buf.getvalue()


def test_render_dispatch_non_table_ignores_object_colors() -> None:
    buf = io.StringIO()
    render_dispatch(
        [{"role": {"display": "Router", "color": "4caf50"}}],
        format=OutputFormat.CSV,
        columns=["role"],
        stream=buf,
        color=True,
        object_colors=True,
    )
    out = buf.getvalue()
    assert "ColoredValue" not in out
    assert "Router" in out
