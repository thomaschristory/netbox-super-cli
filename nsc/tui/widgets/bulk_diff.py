"""Mandatory confirm modal for the cross-record bulk diff.

Renders one block per selected record from the already-computed
:class:`RecordChange` values (sensitive fields masked upstream by ``bulk_diff``).
A record whose patch is empty is shown as unchanged rather than omitted, so the
table stays an honest N-record accounting. Pure presentation: never touches the
client and never recomputes a diff. Confirm dismisses ``True``, cancel ``False``.
"""

from __future__ import annotations

from typing import ClassVar

from nsc.tui.bulk import RecordChange
from nsc.tui.widgets._modal import ConfirmModalBase


class BulkDiffModal(ConfirmModalBase):
    _BODY_ID: ClassVar[str] = "bulk-diff-body"

    def __init__(self, changes: list[RecordChange]) -> None:
        super().__init__()
        self._changes = changes

    def render_text(self) -> str:
        lines: list[str] = ["[b]Review bulk changes[/b]", ""]
        if not self._changes:
            lines.append("[dim]No changes.[/dim]")
        for change in self._changes:
            lines.append(f"record #{change.record_id}")
            if not change.rows:
                lines.append("  [dim]unchanged[/dim]")
                continue
            for row in change.rows:
                lines.append(f"  {row.field}: {row.old_display} -> {row.new_display}")
        lines.append("")
        lines.append("[dim]Enter/y confirm · Esc/n cancel[/dim]")
        return "\n".join(lines)
