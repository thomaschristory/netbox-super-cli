from __future__ import annotations

import pytest
from pydantic import ValidationError

from nsc.model.command_model import FieldShape, PrimitiveType
from nsc.tui.forms import DiffRow, WidgetSpec, diff_rows, field_to_widget, fk_display


def test_enum_maps_to_select_carrying_choices() -> None:
    shape = FieldShape(primitive=PrimitiveType.STRING, enum=["active", "offline"])
    spec = field_to_widget("status", shape, ())
    assert spec.kind == "select"
    assert spec.choices == ("active", "offline")
    assert spec.name == "status"


def test_boolean_maps_to_switch() -> None:
    spec = field_to_widget("enabled", FieldShape(primitive=PrimitiveType.BOOLEAN), ())
    assert spec.kind == "switch"


def test_integer_maps_to_number_not_float() -> None:
    spec = field_to_widget("vid", FieldShape(primitive=PrimitiveType.INTEGER), ())
    assert spec.kind == "number"
    assert spec.is_float is False


def test_number_maps_to_number_float() -> None:
    spec = field_to_widget("weight", FieldShape(primitive=PrimitiveType.NUMBER), ())
    assert spec.kind == "number"
    assert spec.is_float is True


def test_string_maps_to_text() -> None:
    spec = field_to_widget("name", FieldShape(primitive=PrimitiveType.STRING), ())
    assert spec.kind == "text"


def test_sensitive_field_masked_regardless_of_primitive() -> None:
    spec = field_to_widget("token", FieldShape(primitive=PrimitiveType.STRING), ("token",))
    assert spec.kind == "masked"
    assert spec.sensitive is True


def test_sensitive_overrides_enum() -> None:
    shape = FieldShape(primitive=PrimitiveType.STRING, enum=["a", "b"])
    spec = field_to_widget("secret", shape, ("secret",))
    assert spec.kind == "masked"
    assert spec.sensitive is True


def test_non_sensitive_field_not_marked_sensitive() -> None:
    spec = field_to_widget("name", FieldShape(primitive=PrimitiveType.STRING), ("token",))
    assert spec.sensitive is False
    assert spec.kind == "text"


def test_nullable_sets_spec_nullable() -> None:
    spec = field_to_widget(
        "comments", FieldShape(primitive=PrimitiveType.STRING, nullable=True), ()
    )
    assert spec.nullable is True


def test_non_nullable_defaults_false() -> None:
    spec = field_to_widget("name", FieldShape(primitive=PrimitiveType.STRING), ())
    assert spec.nullable is False


def test_array_falls_back_to_text() -> None:
    spec = field_to_widget("tags", FieldShape(primitive=PrimitiveType.ARRAY), ())
    assert spec.kind == "text"


def test_object_falls_back_to_text() -> None:
    spec = field_to_widget("custom_fields", FieldShape(primitive=PrimitiveType.OBJECT), ())
    assert spec.kind == "text"


def test_unknown_falls_back_to_text() -> None:
    spec = field_to_widget("mystery", FieldShape(primitive=PrimitiveType.UNKNOWN), ())
    assert spec.kind == "text"


def test_widget_spec_is_frozen() -> None:
    spec = field_to_widget("name", FieldShape(primitive=PrimitiveType.STRING), ())
    assert isinstance(spec, WidgetSpec)
    with pytest.raises(ValidationError):
        spec.kind = "select"  # type: ignore[misc]


def test_fk_display_prefers_display_over_id() -> None:
    assert fk_display({"id": 12, "display": "Top of Rack Switch", "name": "tor"}) == (
        "Top of Rack Switch"
    )


def test_fk_display_falls_back_to_name_then_slug_then_id() -> None:
    assert fk_display({"id": 12, "name": "tor", "slug": "tor-sw"}) == "tor"
    assert fk_display({"id": 12, "slug": "tor-sw"}) == "tor-sw"
    assert fk_display({"id": 12}) == "12"


def test_fk_display_ignores_empty_label_values() -> None:
    # An empty/None label must not shadow a usable lower-priority one.
    assert fk_display({"id": 12, "display": "", "name": "tor"}) == "tor"
    assert fk_display({"id": 12, "display": None, "name": None}) == "12"


def test_fk_display_passes_through_non_dict() -> None:
    assert fk_display("active") == "active"
    assert fk_display(7) == "7"


def test_diff_rows_renders_fk_old_value_as_name() -> None:
    original = {"role": {"id": 12, "display": "Top of Rack Switch"}}
    rows = diff_rows(original, {"role": 5}, ())
    assert rows == [DiffRow(field="role", old_display="Top of Rack Switch", new_display="5")]


def test_diff_rows_new_display_override_used_for_new_value() -> None:
    original = {"role": {"id": 12, "display": "Top of Rack Switch"}}
    rows = diff_rows(original, {"role": 5}, (), {"role": "Leaf Switch"})
    assert rows == [
        DiffRow(field="role", old_display="Top of Rack Switch", new_display="Leaf Switch")
    ]


def test_diff_rows_override_absent_falls_back_to_str() -> None:
    rows = diff_rows({"status": "active"}, {"status": "offline"}, (), {"role": "x"})
    assert rows == [DiffRow(field="status", old_display="active", new_display="offline")]
