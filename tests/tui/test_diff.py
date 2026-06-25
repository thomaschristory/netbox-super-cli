from __future__ import annotations

from nsc.tui.forms import SET_NULL, DiffRow, compute_patch, diff_rows


def test_unchanged_values_omitted() -> None:
    original = {"name": "dev1", "status": "active"}
    staged = {"name": "dev1", "status": "active"}
    assert compute_patch(original, staged) == {}


def test_changed_value_included() -> None:
    original = {"name": "dev1"}
    staged = {"name": "dev2"}
    assert compute_patch(original, staged) == {"name": "dev2"}


def test_set_null_sentinel_emits_none() -> None:
    original = {"comments": "hello"}
    staged = {"comments": SET_NULL}
    assert compute_patch(original, staged) == {"comments": None}


def test_set_null_on_already_null_is_omitted() -> None:
    original = {"comments": None}
    staged = {"comments": SET_NULL}
    assert compute_patch(original, staged) == {}


def test_same_value_omitted() -> None:
    original = {"name": "dev1", "vid": 10}
    staged = {"name": "dev1", "vid": 10}
    assert compute_patch(original, staged) == {}


def test_fk_int_replacing_nested_dict_with_different_id_included() -> None:
    original = {"site": {"id": 5, "name": "AMS1", "url": "https://nb/api/dcim/sites/5/"}}
    staged = {"site": 7}
    assert compute_patch(original, staged) == {"site": 7}


def test_fk_int_matching_nested_dict_id_omitted() -> None:
    original = {"site": {"id": 5, "name": "AMS1", "url": "https://nb/api/dcim/sites/5/"}}
    staged = {"site": 5}
    assert compute_patch(original, staged) == {}


def test_field_only_in_staged_included() -> None:
    original: dict[str, object] = {}
    staged = {"name": "new"}
    assert compute_patch(original, staged) == {"name": "new"}


def test_field_only_in_original_omitted() -> None:
    original = {"name": "dev1", "untouched": "x"}
    staged = {"name": "dev2"}
    assert compute_patch(original, staged) == {"name": "dev2"}


def test_diff_rows_basic() -> None:
    original = {"name": "dev1"}
    staged = {"name": "dev2"}
    patch = compute_patch(original, staged)
    rows = diff_rows(original, patch, sensitive_paths=())
    assert rows == [DiffRow(field="name", old_display="dev1", new_display="dev2")]


def test_diff_rows_masks_sensitive() -> None:
    original = {"token": "abc123"}
    staged = {"token": "xyz789"}
    patch = compute_patch(original, staged)
    rows = diff_rows(original, patch, sensitive_paths=("token",))
    assert rows == [DiffRow(field="token", old_display="****", new_display="****")]


def test_diff_rows_set_null_shows_none() -> None:
    original = {"comments": "hi"}
    staged = {"comments": SET_NULL}
    patch = compute_patch(original, staged)
    rows = diff_rows(original, patch, sensitive_paths=())
    assert rows == [DiffRow(field="comments", old_display="hi", new_display="None")]


def test_diff_rows_nested_fk_old_display_uses_name() -> None:
    # Issue #97: the old value renders the FK's human label, not its numeric id.
    original = {"site": {"id": 5, "name": "AMS1"}}
    staged = {"site": 7}
    patch = compute_patch(original, staged)
    rows = diff_rows(original, patch, sensitive_paths=())
    assert rows[0].field == "site"
    assert rows[0].old_display == "AMS1"
    assert rows[0].new_display == "7"


def test_diff_rows_missing_original_shows_empty_old() -> None:
    original: dict[str, object] = {}
    staged = {"name": "new"}
    patch = compute_patch(original, staged)
    rows = diff_rows(original, patch, sensitive_paths=())
    assert rows == [DiffRow(field="name", old_display="", new_display="new")]
