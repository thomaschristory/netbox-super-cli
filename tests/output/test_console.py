from __future__ import annotations

import io

from nsc.output._console import make_console


def test_color_console_does_not_auto_highlight_parens() -> None:
    """Rich's auto-highlighter bolds parens on plain text — make_console must disable it."""
    buf = io.StringIO()
    make_console(buf, color=True).print("(no records)")
    out = buf.getvalue()
    assert "(no records)" in out
    assert "\x1b[" not in out


def test_color_console_does_not_auto_highlight_numbers() -> None:
    """Rich's auto-highlighter colorizes IP-like tokens — make_console must disable it."""
    buf = io.StringIO()
    make_console(buf, color=True).print("192.168.1.1")
    out = buf.getvalue()
    assert "192.168.1.1" in out
    assert "\x1b[" not in out


def test_color_console_still_renders_explicit_markup() -> None:
    """highlight=False disables auto-highlighting only — intentional markup still renders."""
    buf = io.StringIO()
    make_console(buf, color=True).print("[green]active[/]")
    out = buf.getvalue()
    assert "active" in out
    assert "\x1b[" in out


def test_no_color_console_emits_no_ansi() -> None:
    buf = io.StringIO()
    make_console(buf, color=False).print("[green]active[/]")
    out = buf.getvalue()
    assert "active" in out
    assert "\x1b[" not in out
