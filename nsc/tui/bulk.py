"""Pure, framework-free cross-record bulk diff.

Expands a single chosen field->value mapping (the bulk "set") across many
selected records, reusing :func:`forms.compute_patch` and :func:`forms.diff_rows`
so FK nested-dict-by-id comparison, ``SET_NULL`` handling, and sensitive masking
behave identically to single-record edits. No Textual, no http.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from nsc.tui.forms import DiffRow, compute_patch, diff_rows


class RecordChange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: object
    patch: dict[str, object]
    rows: list[DiffRow]


def bulk_diff(
    selected: list[dict[str, object]],
    bulk_set: dict[str, object],
    sensitive_paths: tuple[str, ...],
) -> list[RecordChange]:
    """Compute the per-record patch and diff rows for a uniform bulk ``set``.

    Order of ``selected`` is preserved. A field whose new value equals a
    record's current value contributes no patch entry and no row for that
    record, so heterogeneous current values yield different changed subsets.
    """
    changes: list[RecordChange] = []
    for record in selected:
        patch = compute_patch(record, bulk_set)
        rows = diff_rows(record, patch, sensitive_paths)
        changes.append(RecordChange(record_id=record.get("id"), patch=patch, rows=rows))
    return changes
