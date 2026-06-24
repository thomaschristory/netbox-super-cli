from __future__ import annotations

from nsc.tui.bulk import BulkFailure, BulkResult
from nsc.tui.widgets.bulk_summary import BulkSummaryModal


def test_render_reports_success_and_failure_counts() -> None:
    result = BulkResult(
        successes=[1, 2],
        failures=[BulkFailure(record_id=3, error="NetBox API 400: bad request")],
        skipped=[],
    )
    text = BulkSummaryModal(result).render_text()
    assert "2 succeeded, 1 failed" in text
    assert "#3" in text
    assert "bad request" in text


def test_render_includes_skipped_as_unchanged() -> None:
    result = BulkResult(successes=[1], failures=[], skipped=[2, 3])
    text = BulkSummaryModal(result).render_text()
    assert "1 succeeded, 0 failed, 2 unchanged" in text


def test_render_all_success_has_no_failure_section() -> None:
    result = BulkResult(successes=[1, 2, 3], failures=[], skipped=[])
    text = BulkSummaryModal(result).render_text()
    assert "3 succeeded, 0 failed" in text
    assert "Failures" not in text
