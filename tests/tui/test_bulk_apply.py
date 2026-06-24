from __future__ import annotations

from nsc.http.errors import NetBoxAPIError
from nsc.tui.bulk import BulkFailure, BulkResult, RecordChange, apply_bulk


def _change(record_id: object, patch: dict[str, object]) -> RecordChange:
    return RecordChange(record_id=record_id, patch=patch, rows=[])


def test_all_succeed() -> None:
    changes = [
        _change(1, {"status": "offline"}),
        _change(2, {"status": "offline"}),
        _change(3, {"status": "offline"}),
    ]
    attempted: list[object] = []

    def patch_fn(change: RecordChange) -> None:
        attempted.append(change.record_id)

    result = apply_bulk(changes, patch_fn)

    assert isinstance(result, BulkResult)
    assert result.successes == [1, 2, 3]
    assert result.failures == []
    assert result.skipped == []
    assert attempted == [1, 2, 3]


def test_partial_failure_does_not_stop_early() -> None:
    changes = [
        _change(1, {"status": "offline"}),
        _change(2, {"status": "offline"}),
        _change(3, {"status": "offline"}),
    ]
    attempted: list[object] = []

    def patch_fn(change: RecordChange) -> None:
        attempted.append(change.record_id)
        if change.record_id == 2:
            raise NetBoxAPIError(
                status_code=400,
                url="https://nb/api/dcim/devices/2/",
                body_snippet="bad request",
                headers={},
            )

    result = apply_bulk(changes, patch_fn)

    assert result.successes == [1, 3]
    assert result.skipped == []
    assert attempted == [1, 2, 3]
    assert len(result.failures) == 1
    failure = result.failures[0]
    assert isinstance(failure, BulkFailure)
    assert failure.record_id == 2
    assert "400" in failure.error
    assert "bad request" in failure.error


def test_empty_patch_is_skipped_not_called() -> None:
    changes = [
        _change(1, {"status": "offline"}),
        _change(2, {}),
        _change(3, {"status": "offline"}),
    ]
    attempted: list[object] = []

    def patch_fn(change: RecordChange) -> None:
        attempted.append(change.record_id)

    result = apply_bulk(changes, patch_fn)

    assert result.successes == [1, 3]
    assert result.skipped == [2]
    assert result.failures == []
    assert attempted == [1, 3]


def test_every_record_in_exactly_one_bucket() -> None:
    changes = [
        _change(1, {"status": "offline"}),
        _change(2, {"status": "offline"}),
        _change(3, {}),
        _change(4, {"status": "offline"}),
    ]

    def patch_fn(change: RecordChange) -> None:
        if change.record_id == 2:
            raise NetBoxAPIError(
                status_code=500,
                url="https://nb/api/dcim/devices/2/",
                body_snippet="boom",
                headers={},
            )

    result = apply_bulk(changes, patch_fn)

    seen = set(result.successes) | {f.record_id for f in result.failures} | set(result.skipped)
    assert seen == {1, 2, 3, 4}
    total = len(result.successes) + len(result.failures) + len(result.skipped)
    assert total == len(changes)


def test_progress_callback_once_per_attempted_record() -> None:
    changes = [
        _change(1, {"status": "offline"}),
        _change(2, {}),
        _change(3, {"status": "offline"}),
    ]
    progress: list[tuple[int, int]] = []

    def patch_fn(change: RecordChange) -> None:
        pass

    def on_progress(index: int, total: int) -> None:
        progress.append((index, total))

    apply_bulk(changes, patch_fn, on_progress=on_progress)

    assert progress == [(1, 3), (2, 3), (3, 3)]
