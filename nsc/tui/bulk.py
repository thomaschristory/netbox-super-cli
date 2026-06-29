"""Pure, framework-free cross-record bulk diff.

Expands a single chosen field->value mapping (the bulk "set") across many
selected records, reusing :func:`forms.compute_patch` and :func:`forms.diff_rows`
so FK nested-dict-by-id comparison, ``SET_NULL`` handling, and sensitive masking
behave identically to single-record edits. No Textual, no http.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from nsc.http.errors import NetBoxAPIError, NetBoxClientError
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
    new_displays: dict[str, str] | None = None,
    field_labels: dict[str, str] | None = None,
) -> list[RecordChange]:
    """Compute the per-record patch and diff rows for a uniform bulk ``set``.

    Order of ``selected`` is preserved. A field whose new value equals a
    record's current value contributes no patch entry and no row for that
    record, so heterogeneous current values yield different changed subsets.
    ``new_displays`` maps a field to the human label of its chosen FK value so
    the diff renders the name rather than the id. ``field_labels`` maps a field
    key to its human label so ``custom_fields.<name>`` rows aren't shown raw.
    """
    changes: list[RecordChange] = []
    for record in selected:
        patch = compute_patch(record, bulk_set)
        rows = diff_rows(record, patch, sensitive_paths, new_displays, field_labels)
        changes.append(RecordChange(record_id=record.get("id"), patch=patch, rows=rows))
    return changes


def _comparable(value: object) -> object:
    """Normalise an FK nested object to its id so values compare by identity."""
    if isinstance(value, dict) and "id" in value:
        return value["id"]
    return value


def shared_values(records: list[dict[str, object]], field_names: list[str]) -> dict[str, object]:
    """Value each field holds in common across all records (else absent).

    Used to prepopulate the bulk form so an opted-in field starts from the
    records' shared value. Fields where the records disagree, or whose shared
    value is ``None``/missing, are omitted (left blank).
    """
    shared: dict[str, object] = {}
    for name in field_names:
        values = [_comparable(record.get(name)) for record in records]
        first = values[0] if values else None
        if first is not None and all(value == first for value in values):
            shared[name] = first
    return shared


class BulkFailure(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: object
    error: str


class BulkResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    successes: list[object]
    failures: list[BulkFailure]
    skipped: list[object]


def apply_bulk(
    changes: list[RecordChange],
    patch_fn: Callable[[RecordChange], None],
    on_progress: Callable[[int, int], None] | None = None,
) -> BulkResult:
    """Apply ``patch_fn`` to each change, aggregating per-record outcomes.

    A change with an empty patch is skipped without calling ``patch_fn``. The
    loop never re-raises: an HTTP error for one record is recorded and the
    remaining records are still attempted, so a single failure cannot silently
    abort the batch. Every input change lands in exactly one of
    ``successes``/``failures``/``skipped``.
    """
    successes: list[object] = []
    failures: list[BulkFailure] = []
    skipped: list[object] = []
    total = len(changes)
    for index, change in enumerate(changes, start=1):
        if on_progress is not None:
            on_progress(index, total)
        if not change.patch:
            skipped.append(change.record_id)
            continue
        try:
            patch_fn(change)
        except (NetBoxAPIError, NetBoxClientError) as exc:
            failures.append(BulkFailure(record_id=change.record_id, error=exc.render_for_cli()))
        else:
            successes.append(change.record_id)
    return BulkResult(successes=successes, failures=failures, skipped=skipped)
