"""Server text shown on a terminal can't carry control sequences or markup (#206)."""

from __future__ import annotations

import io

from nsc.output import table
from nsc.output.sanitize import printable, safe_markup

EVIL = "x\x1b]0;pwned\x07\x1b[2J\u202e"


def test_printable_escapes_control_and_format_characters() -> None:
    assert printable(EVIL) == "x\\x1b]0;pwned\\x07\\x1b[2J\\u202e"


def test_printable_keeps_newlines_tabs_and_ordinary_unicode() -> None:
    text = "café ☃ 東京\tcol\nnext"
    assert printable(text) == text


def test_safe_markup_also_escapes_rich_markup() -> None:
    assert safe_markup("[bold]x\x1b[/]") == "\\[bold]x\\x1b\\[/]"


def _table(data: object, *, color: bool) -> str:
    buf = io.StringIO()
    table.render(data, stream=buf, color=color)  # type: ignore[arg-type]
    return buf.getvalue()


def test_table_cells_and_headers_are_sanitized() -> None:
    for color in (False, True):
        out = _table([{"name": EVIL, f"k{EVIL}": "v"}], color=color)
        assert "\x1b]0;pwned" not in out
        assert "\x07" not in out
        assert "\u202e" not in out
        assert "pwned" in out


def test_table_headers_are_not_parsed_as_markup() -> None:
    out = _table([{"[red]key[/]": "v"}], color=False)
    assert "[red]key[/]" in out


def test_explain_panel_is_sanitized() -> None:
    from nsc.output.explain import ExplainTrace, render_to_rich_stdout  # noqa: PLC0415

    trace = ExplainTrace(
        operation_id=f"op{EVIL}",
        operation_summary=f"summary{EVIL}",
        method_reasoning=f"m{EVIL}",
        url_reasoning=f"u{EVIL}",
    )
    buf = io.StringIO()
    render_to_rich_stdout(trace, stream=buf, color=False)
    out = buf.getvalue()
    assert "\x1b" not in out
    assert "\u202e" not in out
