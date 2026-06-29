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


def test_diff_rows_uses_field_label_for_custom_field_key() -> None:
    rows = diff_rows(
        {"custom_fields.tier": "silver"},
        {"custom_fields.tier": "gold"},
        (),
        field_labels={"custom_fields.tier": "Tier"},
    )
    assert rows == [DiffRow(field="Tier", old_display="silver", new_display="gold")]


def test_diff_rows_field_label_absent_falls_back_to_raw_key() -> None:
    rows = diff_rows({"status": "active"}, {"status": "offline"}, (), field_labels={})
    assert rows == [DiffRow(field="status", old_display="active", new_display="offline")]


# --- #134: custom-field expansion, tags multi-select, payload nesting ---

from nsc.savedfilters.custom_fields import CustomFieldDef  # noqa: E402
from nsc.savedfilters.tags import TagDef  # noqa: E402
from nsc.tui.forms import (  # noqa: E402
    custom_field_widget,
    expand_custom_fields,
    flatten_custom_fields,
    nest_custom_fields,
    tag_slugs,
    tags_payload,
    tags_widget_spec,
)


def test_custom_field_widget_maps_types() -> None:
    assert custom_field_widget(CustomFieldDef("a", "A", type="text")).kind == "text"
    assert custom_field_widget(CustomFieldDef("a", "A", type="integer")).kind == "number"
    dec = custom_field_widget(CustomFieldDef("a", "A", type="decimal"))
    assert dec.kind == "number" and dec.is_float is True
    assert custom_field_widget(CustomFieldDef("a", "A", type="boolean")).kind == "switch"
    sel = custom_field_widget(CustomFieldDef("a", "A", type="select", choices=("x", "y")))
    assert sel.kind == "select" and sel.choices == ("x", "y")
    ms = custom_field_widget(CustomFieldDef("a", "A", type="multiselect", choices=("x", "y")))
    assert ms.kind == "multi_select"


def test_custom_field_widget_names_are_dotted() -> None:
    spec = custom_field_widget(CustomFieldDef("rack_role", "Rack Role"))
    assert spec.name == "custom_fields.rack_role"


def test_expand_custom_fields_one_spec_each() -> None:
    defs = {
        "a": CustomFieldDef("a", "A", type="text"),
        "b": CustomFieldDef("b", "B", type="integer"),
    }
    specs = expand_custom_fields(defs)
    assert [s.name for s in specs] == ["custom_fields.a", "custom_fields.b"]


def test_tags_widget_spec_carries_options_and_selected() -> None:
    tags = (TagDef("Prod", "prod", "ff0000"), TagDef("Edge", "edge", None))
    spec = tags_widget_spec("tags", tags, ("prod",))
    assert spec.kind == "multi_select"
    assert spec.options == (("Prod", "prod"), ("Edge", "edge"))
    assert spec.selected == ("prod",)


def test_tag_slugs_extracts_from_record_list() -> None:
    value = [{"slug": "prod", "name": "Prod"}, {"name": "edge"}]
    assert tag_slugs(value) == ("prod", "edge")
    assert tag_slugs(None) == ()


def test_tags_payload_builds_name_slug_objects() -> None:
    tags = (TagDef("Prod", "prod", None), TagDef("Edge", "edge", None))
    assert tags_payload(("prod",), tags) == [{"name": "Prod", "slug": "prod"}]
    # Unknown slug falls back to itself.
    assert tags_payload(("ghost",), tags) == [{"name": "ghost", "slug": "ghost"}]


def test_flatten_custom_fields_adds_dotted_keys() -> None:
    rec = {"name": "x", "custom_fields": {"tier": "gold", "n": 3}}
    flat = flatten_custom_fields(rec)
    assert flat["custom_fields.tier"] == "gold"
    assert flat["custom_fields.n"] == 3
    # Original is not mutated.
    assert "custom_fields.tier" not in rec


def test_flatten_custom_fields_noop_without_cf() -> None:
    assert flatten_custom_fields({"name": "x"}) == {"name": "x"}


def test_nest_custom_fields_folds_dotted_keys() -> None:
    patch = {"name": "x", "custom_fields.tier": "silver", "custom_fields.n": None}
    nested = nest_custom_fields(patch)
    assert nested == {"name": "x", "custom_fields": {"tier": "silver", "n": None}}


def test_nest_custom_fields_passthrough_without_cf() -> None:
    assert nest_custom_fields({"name": "x"}) == {"name": "x"}
