from __future__ import annotations

import pytest
from pydantic import ValidationError

from nsc.model.command_model import FieldShape, PrimitiveType
from nsc.tui.forms import WidgetSpec, field_to_widget


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
