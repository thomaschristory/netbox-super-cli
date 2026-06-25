from __future__ import annotations

import pytest
from pydantic import ValidationError

from nsc.tui.bulk import RecordChange, bulk_diff, shared_values
from nsc.tui.forms import SET_NULL, DiffRow


def test_shared_values_returns_only_fields_all_records_agree_on() -> None:
    records = [
        {"id": 1, "status": "active", "site": {"id": 3, "display": "HQ"}, "role": "leaf"},
        {"id": 2, "status": "active", "site": {"id": 3, "display": "HQ"}, "role": "spine"},
    ]
    shared = shared_values(records, ["status", "site", "role", "absent"])
    assert shared == {"status": "active", "site": 3}  # FK normalised to id
    assert "role" not in shared  # records disagree
    assert "absent" not in shared  # missing everywhere -> None -> omitted


def test_shared_values_omits_none_and_handles_empty() -> None:
    assert shared_values([{"id": 1, "x": None}, {"id": 2, "x": None}], ["x"]) == {}
    assert shared_values([], ["x"]) == {}


def test_uniform_set_yields_per_record_changes_in_order() -> None:
    selected = [
        {"id": 1, "status": "active"},
        {"id": 2, "status": "active"},
    ]
    result = bulk_diff(selected, {"status": "offline"}, ())
    assert [rc.record_id for rc in result] == [1, 2]
    assert all(isinstance(rc, RecordChange) for rc in result)
    for rc in result:
        assert rc.patch == {"status": "offline"}
        assert rc.rows == [DiffRow(field="status", old_display="active", new_display="offline")]


def test_field_value_equal_to_current_yields_no_row_for_that_record() -> None:
    selected = [
        {"id": 1, "status": "active"},
        {"id": 2, "status": "offline"},
    ]
    result = bulk_diff(selected, {"status": "offline"}, ())
    first = result[0]
    assert first.record_id == 1
    assert first.patch == {"status": "offline"}
    assert first.rows == [DiffRow(field="status", old_display="active", new_display="offline")]
    # Record 2 already 'offline' -> no diff, empty patch, empty rows.
    second = result[1]
    assert second.record_id == 2
    assert second.patch == {}
    assert second.rows == []


def test_heterogeneous_current_values_give_different_changed_subsets() -> None:
    selected = [
        {"id": 1, "status": "active", "tenant": {"id": 5}},
        {"id": 2, "status": "offline", "tenant": {"id": 7}},
    ]
    result = bulk_diff(selected, {"status": "offline", "tenant": 7}, ())
    by_id = {rc.record_id: rc for rc in result}
    assert by_id[1].patch == {"status": "offline", "tenant": 7}
    assert {row.field for row in by_id[1].rows} == {"status", "tenant"}
    # Record 2 already matches both -> no-op.
    assert by_id[2].patch == {}
    assert by_id[2].rows == []


def test_fk_nested_dict_by_id_no_op_when_id_matches() -> None:
    selected = [{"id": 1, "site": {"id": 9, "name": "dc1"}}]
    result = bulk_diff(selected, {"site": 9}, ())
    assert result[0].patch == {}
    assert result[0].rows == []


def test_fk_nested_dict_by_id_changes_when_id_differs() -> None:
    selected = [{"id": 1, "site": {"id": 9, "name": "dc1"}}]
    result = bulk_diff(selected, {"site": 3}, ())
    assert result[0].patch == {"site": 3}
    # Old value renders the FK's human label, not its numeric id.
    assert result[0].rows == [DiffRow(field="site", old_display="dc1", new_display="3")]


def test_fk_new_display_override_renders_chosen_label() -> None:
    selected = [{"id": 1, "site": {"id": 9, "name": "dc1"}}]
    result = bulk_diff(selected, {"site": 3}, (), {"site": "dc2"})
    assert result[0].patch == {"site": 3}
    assert result[0].rows == [DiffRow(field="site", old_display="dc1", new_display="dc2")]


def test_set_null_on_already_null_record_yields_no_row() -> None:
    selected = [{"id": 1, "comments": None}]
    result = bulk_diff(selected, {"comments": SET_NULL}, ())
    assert result[0].patch == {}
    assert result[0].rows == []


def test_set_null_on_non_null_record_emits_none_patch() -> None:
    selected = [{"id": 1, "comments": "hi"}]
    result = bulk_diff(selected, {"comments": SET_NULL}, ())
    assert result[0].patch == {"comments": None}
    assert result[0].rows == [DiffRow(field="comments", old_display="hi", new_display="None")]


def test_sensitive_field_masked_in_rows() -> None:
    selected = [{"id": 1, "token": "old-secret"}]
    result = bulk_diff(selected, {"token": "new-secret"}, ("token",))
    assert result[0].patch == {"token": "new-secret"}
    assert result[0].rows == [DiffRow(field="token", old_display="****", new_display="****")]


def test_record_change_is_frozen() -> None:
    selected = [{"id": 1, "status": "active"}]
    rc = bulk_diff(selected, {"status": "offline"}, ())[0]
    with pytest.raises(ValidationError):
        rc.record_id = 2  # type: ignore[misc]
