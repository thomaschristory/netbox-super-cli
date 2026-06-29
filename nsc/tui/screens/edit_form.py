"""EditForm — build staging widgets from an operation's request body.

Each field maps to a concrete Textual widget via the pure ``forms`` layer.
Widget changes mutate the screen's staging buffer only; nothing reaches the
network until an explicit save (handled by a later phase).
"""

from __future__ import annotations

from typing import Any, ClassVar, Protocol

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Select, SelectionList, Switch
from textual.widgets.selection_list import Selection

from nsc.http.errors import NetBoxAPIError, NetBoxClientError
from nsc.model.command_model import CommandModel, Operation
from nsc.savedfilters.custom_fields import CustomFieldDef
from nsc.savedfilters.tags import TagDef
from nsc.tui._bindings import textual_bindings
from nsc.tui.errors import api_error_message
from nsc.tui.fk import is_fk_value, resolve_fk_target
from nsc.tui.forms import (
    SET_NULL,
    WidgetSpec,
    compute_patch,
    decode_field_id,
    diff_rows,
    encode_field_id,
    expand_custom_fields,
    field_to_widget,
    fk_display,
    flatten_custom_fields,
    nest_custom_fields,
    tag_slugs,
    tags_payload,
    tags_widget_spec,
)
from nsc.tui.view import detail_path


class _Client(Protocol):
    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any: ...

    def patch(
        self,
        path: str,
        *,
        json: Any | None = None,
        operation_id: str | None = None,
        sensitive_paths: tuple[str, ...] = (),
    ) -> dict[str, Any]: ...

    def post(
        self,
        path: str,
        *,
        json: Any | None = None,
        operation_id: str | None = None,
        sensitive_paths: tuple[str, ...] = (),
    ) -> dict[str, Any]: ...


def _record_value(record: dict[str, Any], name: str) -> Any:
    value = record.get(name)
    if isinstance(value, dict) and "id" in value:
        return value["id"]
    return value


class EditForm(Screen[None]):
    BINDINGS: ClassVar[list[BindingType]] = textual_bindings("edit")

    def __init__(
        self,
        model: CommandModel,
        client: _Client,
        tag: str,
        resource_name: str,
        operation: Operation,
        record: dict[str, Any],
        custom_field_defs: dict[str, CustomFieldDef] | None = None,
        available_tags: tuple[TagDef, ...] | None = None,
    ) -> None:
        super().__init__()
        self._model = model
        self._client = client
        self._tag = tag
        self._resource_name = resource_name
        self._op = operation
        # Explode custom_fields into custom_fields.<name> keys so the per-field
        # widgets seed and diff individually; the patch is re-nested before send.
        self._record = flatten_custom_fields(record)
        self._cf_defs = custom_field_defs
        self._tags = available_tags
        self._specs: dict[str, WidgetSpec] = {}
        self._fk_labels: dict[str, str] = {}
        self.staged: dict[str, Any] = {}
        self._create_mode = operation.http_method.upper() == "POST"
        if self._create_mode:
            self.title = f"Create {resource_name}"
        else:
            self.title = f"Edit {resource_name} #{record.get('id', '?')}"

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="edit-form-body"):
            body = self._op.request_body
            fields = body.fields if body is not None else {}
            sensitive = body.sensitive_paths if body is not None else ()
            for name, field in fields.items():
                for spec in self._specs_for(name, field, sensitive):
                    self._specs[spec.name] = spec
                    yield from self._compose_field(spec.name, spec)
            yield Button("Save", id="save", classes="edit-save")
        yield Footer()

    def _specs_for(self, name: str, field: Any, sensitive: tuple[str, ...]) -> list[WidgetSpec]:
        """Widget spec(s) for a body field — expanding custom_fields and tags."""
        if name == "custom_fields" and self._cf_defs:
            return expand_custom_fields(self._cf_defs)
        if name == "tags" and self._tags is not None:
            current = tag_slugs(self._record.get("tags"))
            return [tags_widget_spec(name, self._tags, current)]
        return [field_to_widget(name, field, sensitive)]

    def _compose_field(self, name: str, spec: WidgetSpec) -> ComposeResult:
        value = _record_value(self._record, name)
        with Horizontal(classes="edit-field"):
            yield Label(name, classes="edit-label")
            yield from self._compose_widget(name, spec, value)
            if spec.nullable and spec.kind != "multi_select":
                yield Button("∅", id=f"setnull-{encode_field_id(name)}", classes="edit-setnull")

    def _compose_widget(self, name: str, spec: WidgetSpec, value: Any) -> ComposeResult:
        wid = f"field-{encode_field_id(name)}"
        if spec.kind == "multi_select":
            # Tags seed via spec.selected; a custom-field multiselect seeds from
            # the record's current list value.
            current = set(spec.selected)
            if not current and isinstance(value, list):
                current = {str(v) for v in value}
            yield SelectionList[str](
                *(Selection(label, val, val in current) for label, val in spec.options),
                id=wid,
                classes="edit-multiselect",
            )
            return
        if self._is_fk(name, spec):
            yield from self._compose_fk(name, value)
            return
        if spec.kind == "select":
            options = [(choice, choice) for choice in spec.choices]
            select_value = value if value in spec.choices else Select.NULL
            yield Select(options, value=select_value, id=wid, allow_blank=True)
            return
        if spec.kind == "switch":
            yield Switch(value=bool(value), id=wid)
            return
        text = "" if value is None else str(value)
        yield Input(value=text, password=spec.sensitive, id=wid)

    def _is_fk(self, name: str, spec: WidgetSpec) -> bool:
        # Writable FK fields type as oneOf[int, brief] -> UNKNOWN -> `text`, so a
        # `number`-only gate would miss real relations (role, site, tenant…). Key
        # off the record's nested object instead; exclude enum/bool/secret/float.
        if spec.kind in ("select", "switch", "masked") or spec.is_float:
            return False
        return name.endswith("_id") or is_fk_value(self._record.get(name))

    def _compose_fk(self, name: str, value: Any) -> ComposeResult:
        target = resolve_fk_target(name, self._record.get(name), self._model)
        if target.kind == "raw_id":
            text = "" if value is None else str(value)
            yield Input(value=text, id=f"field-{name}")
            if target.hint:
                yield Label(target.hint, classes="edit-fk-hint")
            return
        nested = self._record.get(name)
        current = (
            fk_display(nested)
            if isinstance(nested, dict)
            else ("" if value is None else str(value))
        )
        yield Button(f"{name}: {current}", id=f"fk-{name}", classes="edit-fk")

    @staticmethod
    def _field_name(ident: str | None) -> str | None:
        if ident is None or not ident.startswith("field-"):
            return None
        return decode_field_id(ident.removeprefix("field-"))

    def on_input_changed(self, event: Input.Changed) -> None:
        name = self._field_name(event.input.id)
        if name is None:
            return
        self.staged[name] = self._coerce_input(name, event.value)

    def _coerce_input(self, name: str, raw: str) -> Any:
        spec = self._specs.get(name)
        numeric = (spec is not None and spec.kind == "number") or self._is_fk_field(name, spec)
        if not numeric:
            return raw
        if raw == "":
            return None
        try:
            return float(raw) if spec is not None and spec.is_float else int(raw)
        except ValueError:
            return raw

    def _is_fk_field(self, name: str, spec: WidgetSpec | None) -> bool:
        return spec is not None and self._is_fk(name, spec)

    def on_switch_changed(self, event: Switch.Changed) -> None:
        name = self._field_name(event.switch.id)
        if name is None:
            return
        self.staged[name] = event.value

    def on_select_changed(self, event: Select.Changed) -> None:
        name = self._field_name(event.select.id)
        if name is None:
            return
        self.staged[name] = None if event.value is Select.NULL else event.value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        ident = event.button.id
        if ident is None:
            return
        if ident == "save":
            self.action_save()
            return
        if ident.startswith("setnull-"):
            field = decode_field_id(ident.removeprefix("setnull-"))
            self.staged[field] = SET_NULL
            # Drop any picked label so the diff can't show a name while nulling.
            self._fk_labels.pop(field, None)
            return
        if ident.startswith("fk-"):
            self._open_picker(ident.removeprefix("fk-"))

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged[str]) -> None:
        name = self._field_name(event.selection_list.id)
        if name is None:
            return
        selected = tuple(str(v) for v in event.selection_list.selected)
        # Only stage when the selection actually changed (by set), so an
        # unchanged pre-seeded selection — regardless of order — doesn't force a
        # spurious patch.
        if name == "tags":
            if set(selected) == set(tag_slugs(self._record.get("tags"))):
                self.staged.pop(name, None)
            else:
                self.staged[name] = tags_payload(selected, self._tags or ())
            return
        original = self._record.get(name)
        original_set = {str(v) for v in original} if isinstance(original, list) else set()
        if set(selected) == original_set:
            self.staged.pop(name, None)
        else:
            self.staged[name] = list(selected)

    def _open_picker(self, name: str) -> None:
        target = resolve_fk_target(name, self._record.get(name), self._model)
        if target.list_op is None:
            return
        from nsc.tui.screens.record_picker import RecordPicker  # noqa: PLC0415

        def _stage(result: tuple[int, str] | None) -> None:
            if result is not None:
                self.staged[name] = result[0]
                self._fk_labels[name] = result[1]
                self.query_one(f"#fk-{name}", Button).label = f"{name}: {result[1]}"

        self.app.push_screen(RecordPicker(self._client, target.list_op, target.current_id), _stage)

    def action_save(self) -> None:
        patch = compute_patch(self._record, self.staged)
        if not patch:
            self.notify("No changes to save.")
            return
        body = self._op.request_body
        sensitive = body.sensitive_paths if body is not None else ()
        from nsc.tui.widgets.diff import DiffModal  # noqa: PLC0415

        def _on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self._apply_patch(patch, sensitive)

        self.app.push_screen(
            DiffModal(diff_rows(self._record, patch, sensitive, self._fk_labels)), _on_confirm
        )

    def _apply_patch(self, patch: dict[str, Any], sensitive_paths: tuple[str, ...]) -> None:
        patch = nest_custom_fields(patch)
        try:
            if self._create_mode:
                self._client.post(
                    self._op.path,
                    json=patch,
                    operation_id=self._op.operation_id,
                    sensitive_paths=sensitive_paths,
                )
            else:
                self._client.patch(
                    detail_path(self._op.path, self._record.get("id")),
                    json=patch,
                    operation_id=self._op.operation_id,
                    sensitive_paths=sensitive_paths,
                )
        except (NetBoxAPIError, NetBoxClientError) as exc:
            self.notify(api_error_message(exc), severity="error", timeout=8)
            return
        self.dismiss()

    def action_go_back(self) -> None:
        if not compute_patch(self._record, self.staged):
            self.dismiss()
            return
        from nsc.tui.widgets.confirm import ConfirmModal  # noqa: PLC0415

        def _on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self.dismiss()

        self.app.push_screen(ConfirmModal("Discard unsaved changes?"), _on_confirm)
