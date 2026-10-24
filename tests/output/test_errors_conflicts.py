"""Branch merge/sync conflicts render as a table on rich stderr (#169)."""

from __future__ import annotations

import io
import json
from typing import Any

from nsc.output.errors import ErrorEnvelope, ErrorType, render_to_json, render_to_rich_stderr


def _conflict(**over: Any) -> dict[str, Any]:
    # Shape returned by netbox-branching 1.2.2 on NetBox 4.7.3 for a 409 merge.
    data: dict[str, Any] = {
        "id": 1,
        "object_type": "extras.tag",
        "object_id": 1,
        "object_repr": "edge",
        "action": {"value": "update", "label": "Updated"},
        "conflicts": ["color", "description"],
        "conflicting_data": {
            "original": {"color": "9e9e9e", "description": ""},
            "branch": {"color": "ff0000", "description": "from-branch"},
            "main": {"color": "00ff00", "description": "from-main"},
        },
        "last_updated": "2026-10-24T21:31:56.653578Z",
    }
    data.update(over)
    return data


def _envelope(*conflicts: Any) -> ErrorEnvelope:
    return ErrorEnvelope(
        error="branch 'my-change' conflicts with main",
        type=ErrorType.CONFLICT,
        details={"branch": "my-change", "conflicts": list(conflicts)},
    )


def _render(env: ErrorEnvelope) -> str:
    buf = io.StringIO()
    render_to_rich_stderr(env, stream=buf)
    return buf.getvalue()


def _rows(out: str) -> list[list[str]]:
    rows = []
    for line in out.splitlines():
        inner = line.strip()[1:-1].strip()  # drop the panel's own border
        if not (inner.startswith("│") and inner.endswith("│")):
            continue
        cells = [c.strip() for c in inner[1:-1].split("│")]
        if len(cells) == 5:
            rows.append(cells)
    return rows


def test_conflicts_render_one_row_per_field_with_all_three_values() -> None:
    out = _render(_envelope(_conflict()))
    assert _rows(out) == [
        ["object", "field", "original", "branch", "main"],
        ["extras.tag edge", "color", "9e9e9e", "ff0000", "00ff00"],
        ["", "description", "", "from-branch", "from-main"],
    ]
    assert "{'id'" not in out


def test_other_details_still_shown_without_raw_conflicts() -> None:
    out = _render(_envelope(_conflict()))
    details = [line for line in out.splitlines() if "details:" in line]
    assert details, out
    assert "my-change" in details[0]
    assert "conflicting_data" not in out


def test_conflict_without_conflicting_data_lists_fields() -> None:
    out = _render(_envelope(_conflict(conflicting_data=None, conflicts=["name"])))
    assert _rows(out)[1] == ["extras.tag edge", "name", "", "", ""]


def test_non_string_values_render_as_json() -> None:
    data = {
        "original": {"tags": []},
        "branch": {"tags": [{"id": 1}]},
        "main": {"tags": None},
    }
    out = _render(_envelope(_conflict(conflicts=["tags"], conflicting_data=data)))
    assert _rows(out)[1] == ["extras.tag edge", "tags", "[]", '[{"id": 1}]', "null"]


def test_unreadable_conflicts_fall_back_to_details_line() -> None:
    out = _render(_envelope())
    assert _rows(out) == []
    assert "conflicts" in out
    out = _render(_envelope("not-a-dict"))
    assert _rows(out) == []
    assert "not-a-dict" in out


def test_json_envelope_is_unchanged() -> None:
    env = _envelope(_conflict())
    assert json.loads(render_to_json(env))["details"]["conflicts"] == [_conflict()]


def test_long_error_message_wraps_instead_of_being_cropped() -> None:
    env = ErrorEnvelope(
        error=(
            "branch 'my-change' has 1 unacknowledged conflict(s); review them and "
            "re-run with --acknowledge-conflicts"
        ),
        type=ErrorType.CONFLICT,
    )
    flat = " ".join(c for line in _render(env).splitlines() for c in line.strip("│ ").split())
    assert "re-run with --acknowledge-conflicts" in flat
