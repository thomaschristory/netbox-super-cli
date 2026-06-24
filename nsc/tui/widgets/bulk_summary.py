"""Acknowledge-only summary modal for a completed bulk PATCH run.

Renders the aggregated :class:`BulkResult` counts and lists each failed record's
id and error message so partial failures are never silent. Pure presentation: it
re-reports an already-computed result and never touches the client. Any key that
dismisses it simply closes the modal — there is no destructive choice to make.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from nsc.tui.bulk import BulkResult


class BulkSummaryModal(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("enter", "dismiss_modal", "Close"),
        ("escape", "dismiss_modal", "Close"),
    ]

    _BODY_ID: ClassVar[str] = "bulk-summary-body"

    def __init__(self, result: BulkResult) -> None:
        super().__init__()
        self._result = result

    def render_text(self) -> str:
        result = self._result
        lines: list[str] = ["[b]Bulk edit complete[/b]", ""]
        summary = f"{len(result.successes)} succeeded, {len(result.failures)} failed"
        if result.skipped:
            summary += f", {len(result.skipped)} unchanged"
        lines.append(summary)
        if result.failures:
            lines.append("")
            lines.append("[b]Failures[/b]")
            for failure in result.failures:
                lines.append(f"  #{failure.record_id}: {failure.error}")
        lines.append("")
        lines.append("[dim]Enter/Esc close[/dim]")
        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        with VerticalScroll(id=self._BODY_ID):
            yield Static(self.render_text(), markup=True)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)
