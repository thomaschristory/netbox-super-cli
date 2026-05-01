"""writes.preflight.check — required + primitive + enum (Phase 3b)."""

from __future__ import annotations

from nsc.cli.writes.input import RawWriteInput
from nsc.cli.writes.preflight import Issue, PreflightResult, check
from nsc.model.command_model import (
    FieldShape,
    HttpMethod,
    Operation,
    PrimitiveType,
    RequestBodyShape,
)


def _op(rbs: RequestBodyShape, *, method: HttpMethod = HttpMethod.POST) -> Operation:
    return Operation(
        operation_id="dcim_devices_create",
        http_method=method,
        path="/api/dcim/devices/",
        request_body=rbs,
    )


def _input(record: dict[str, object]) -> RawWriteInput:
    return RawWriteInput(records=[record], source="fields_only")


def test_no_request_body_passes() -> None:
    op = Operation(
        operation_id="dcim_devices_delete",
        http_method=HttpMethod.DELETE,
        path="/api/dcim/devices/{id}/",
    )
    result = check(_input({}), op)
    assert isinstance(result, PreflightResult)
    assert result.ok is True
    assert result.issues == []


def test_object_or_array_treated_like_object_for_required_check() -> None:
    rbs = RequestBodyShape(
        top_level="object_or_array",
        required=["name"],
        fields={"name": FieldShape(primitive=PrimitiveType.STRING)},
    )
    result = check(_input({"name": "rack-01"}), _op(rbs))
    assert result.ok is True


def test_missing_required_top_level_field() -> None:
    rbs = RequestBodyShape(
        top_level="object",
        required=["name"],
        fields={"name": FieldShape(primitive=PrimitiveType.STRING)},
    )
    result = check(_input({}), _op(rbs))
    assert result.ok is False
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert isinstance(issue, Issue)
    assert issue.kind == "missing_required"
    assert issue.field_path == "name"
    assert issue.record_index == 0


def test_string_required_accepts_empty_string() -> None:
    rbs = RequestBodyShape(
        top_level="object",
        required=["name"],
        fields={"name": FieldShape(primitive=PrimitiveType.STRING)},
    )
    result = check(_input({"name": ""}), _op(rbs))
    assert result.ok is True


def test_integer_field_accepts_int_and_string_int() -> None:
    rbs = RequestBodyShape(
        top_level="object",
        fields={"count": FieldShape(primitive=PrimitiveType.INTEGER)},
    )
    assert check(_input({"count": 42}), _op(rbs)).ok is True
    assert check(_input({"count": "42"}), _op(rbs)).ok is True


def test_integer_field_rejects_bool() -> None:
    rbs = RequestBodyShape(
        top_level="object",
        fields={"count": FieldShape(primitive=PrimitiveType.INTEGER)},
    )
    result = check(_input({"count": True}), _op(rbs))
    assert result.ok is False
    assert result.issues[0].kind == "type_mismatch"
    assert result.issues[0].field_path == "count"
    assert result.issues[0].expected == "integer"


def test_integer_field_rejects_non_numeric_string() -> None:
    rbs = RequestBodyShape(
        top_level="object",
        fields={"count": FieldShape(primitive=PrimitiveType.INTEGER)},
    )
    result = check(_input({"count": "not-a-number"}), _op(rbs))
    assert result.ok is False
    assert result.issues[0].kind == "type_mismatch"


def test_number_accepts_float_int_and_parseable_string() -> None:
    rbs = RequestBodyShape(
        top_level="object",
        fields={"x": FieldShape(primitive=PrimitiveType.NUMBER)},
    )
    for value in (1.5, 2, "3.14"):
        assert check(_input({"x": value}), _op(rbs)).ok is True


def test_boolean_accepts_typical_string_forms() -> None:
    rbs = RequestBodyShape(
        top_level="object",
        fields={"active": FieldShape(primitive=PrimitiveType.BOOLEAN)},
    )
    for value in (True, False, "true", "False", "1", "0", "yes", "NO"):
        assert check(_input({"active": value}), _op(rbs)).ok is True


def test_boolean_rejects_arbitrary_string() -> None:
    rbs = RequestBodyShape(
        top_level="object",
        fields={"active": FieldShape(primitive=PrimitiveType.BOOLEAN)},
    )
    result = check(_input({"active": "maybe"}), _op(rbs))
    assert result.ok is False
    assert result.issues[0].kind == "type_mismatch"
    assert result.issues[0].expected == "boolean"


def test_array_field_must_be_list() -> None:
    rbs = RequestBodyShape(
        top_level="object",
        fields={"tags": FieldShape(primitive=PrimitiveType.ARRAY)},
    )
    assert check(_input({"tags": ["a"]}), _op(rbs)).ok is True
    bad = check(_input({"tags": "a"}), _op(rbs))
    assert bad.ok is False
    assert bad.issues[0].expected == "array"


def test_object_field_must_be_dict() -> None:
    rbs = RequestBodyShape(
        top_level="object",
        fields={"site": FieldShape(primitive=PrimitiveType.OBJECT)},
    )
    assert check(_input({"site": {"name": "x"}}), _op(rbs)).ok is True
    bad = check(_input({"site": "us-east"}), _op(rbs))
    assert bad.ok is False
    assert bad.issues[0].expected == "object"


def test_enum_value_in_set() -> None:
    rbs = RequestBodyShape(
        top_level="object",
        fields={"status": FieldShape(primitive=PrimitiveType.STRING, enum=["active", "planned"])},
    )
    assert check(_input({"status": "active"}), _op(rbs)).ok is True


def test_enum_value_not_in_set() -> None:
    rbs = RequestBodyShape(
        top_level="object",
        fields={"status": FieldShape(primitive=PrimitiveType.STRING, enum=["active", "planned"])},
    )
    result = check(_input({"status": "decommissioned"}), _op(rbs))
    assert result.ok is False
    assert result.issues[0].kind == "enum_invalid"
    assert "active" in (result.issues[0].expected or "")


def test_unknown_field_passes_through_silently() -> None:
    # Spec §4.6: only listed top-level fields are validated; extras pass.
    rbs = RequestBodyShape(
        top_level="object",
        fields={"name": FieldShape(primitive=PrimitiveType.STRING)},
    )
    result = check(_input({"name": "x", "made_up_field": 123}), _op(rbs))
    assert result.ok is True


def test_multi_record_records_indices() -> None:
    rbs = RequestBodyShape(
        top_level="object",
        required=["name"],
        fields={
            "name": FieldShape(primitive=PrimitiveType.STRING),
            "status": FieldShape(primitive=PrimitiveType.STRING, enum=["active", "planned"]),
        },
    )
    raw = RawWriteInput(
        records=[
            {"name": "a"},
            {"status": "bogus"},  # missing required + enum_invalid
        ],
        source="file",
        is_explicit_list=True,
    )
    result = check(raw, _op(rbs))
    assert result.ok is False
    indices = {issue.record_index for issue in result.issues}
    assert indices == {1}  # record 0 is fine
    kinds = {issue.kind for issue in result.issues if issue.record_index == 1}
    assert kinds == {"missing_required", "enum_invalid"}
