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
from textual.widgets import Button, Footer, Header, Input, Label, Select, Switch

from nsc.model.command_model import CommandModel, Operation
from nsc.tui._bindings import textual_bindings
from nsc.tui.fk import resolve_fk_target
from nsc.tui.forms import SET_NULL, WidgetSpec, field_to_widget


class _Client(Protocol):
    def paginate(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int | None = None
    ) -> Any: ...


def _record_value(record: dict[str, Any], name: str) -> Any:
    value = record.get(name)
    if isinstance(value, dict) and "id" in value:
        return value["id"]
    return value


class EditForm(Screen[None]):
    BINDINGS: ClassVar[list[BindingType]] = textual_bindings("detail")

    def __init__(
        self,
        model: CommandModel,
        client: _Client,
        tag: str,
        resource_name: str,
        operation: Operation,
        record: dict[str, Any],
    ) -> None:
        super().__init__()
        self._model = model
        self._client = client
        self._tag = tag
        self._resource_name = resource_name
        self._op = operation
        self._record = record
        self._specs: dict[str, WidgetSpec] = {}
        self.staged: dict[str, Any] = {}
        self.title = f"Edit {resource_name} #{record.get('id', '?')}"

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="edit-form-body"):
            body = self._op.request_body
            fields = body.fields if body is not None else {}
            sensitive = body.sensitive_paths if body is not None else ()
            for name, field in fields.items():
                spec = field_to_widget(name, field, sensitive)
                self._specs[name] = spec
                yield from self._compose_field(name, spec)
        yield Footer()

    def _compose_field(self, name: str, spec: WidgetSpec) -> ComposeResult:
        value = _record_value(self._record, name)
        with Horizontal(classes="edit-field"):
            yield Label(name, classes="edit-label")
            yield from self._compose_widget(name, spec, value)
            if spec.nullable:
                yield Button("∅", id=f"setnull-{name}", classes="edit-setnull")

    def _compose_widget(self, name: str, spec: WidgetSpec, value: Any) -> ComposeResult:
        if self._is_fk(name, spec):
            yield from self._compose_fk(name, value)
            return
        if spec.kind == "select":
            options = [(choice, choice) for choice in spec.choices]
            select_value = value if value in spec.choices else Select.BLANK
            yield Select(options, value=select_value, id=f"field-{name}", allow_blank=True)
            return
        if spec.kind == "switch":
            yield Switch(value=bool(value), id=f"field-{name}")
            return
        text = "" if value is None else str(value)
        yield Input(value=text, password=spec.sensitive, id=f"field-{name}")

    def _is_fk(self, name: str, spec: WidgetSpec) -> bool:
        if spec.kind != "number" or spec.is_float or spec.sensitive:
            return False
        return name.endswith("_id") or isinstance(self._record.get(name), dict)

    def _compose_fk(self, name: str, value: Any) -> ComposeResult:
        target = resolve_fk_target(name, self._record.get(name), self._model)
        if target.kind == "raw_id":
            text = "" if value is None else str(value)
            yield Input(value=text, id=f"field-{name}")
            if target.hint:
                yield Label(target.hint, classes="edit-fk-hint")
            return
        current = "" if value is None else str(value)
        yield Button(f"{name}: {current}", id=f"fk-{name}", classes="edit-fk")

    def on_input_changed(self, event: Input.Changed) -> None:
        ident = event.input.id
        if ident is None or not ident.startswith("field-"):
            return
        self.staged[ident.removeprefix("field-")] = event.value

    def on_switch_changed(self, event: Switch.Changed) -> None:
        ident = event.switch.id
        if ident is None or not ident.startswith("field-"):
            return
        self.staged[ident.removeprefix("field-")] = event.value

    def on_select_changed(self, event: Select.Changed) -> None:
        ident = event.select.id
        if ident is None or not ident.startswith("field-"):
            return
        value = None if event.value is Select.BLANK else event.value
        self.staged[ident.removeprefix("field-")] = value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        ident = event.button.id
        if ident is None:
            return
        if ident.startswith("setnull-"):
            self.staged[ident.removeprefix("setnull-")] = SET_NULL
            return
        if ident.startswith("fk-"):
            self._open_picker(ident.removeprefix("fk-"))

    def _open_picker(self, name: str) -> None:
        target = resolve_fk_target(name, self._record.get(name), self._model)
        if target.list_op is None:
            return
        from nsc.tui.screens.record_picker import RecordPicker  # noqa: PLC0415

        def _stage(result: tuple[int, str] | None) -> None:
            if result is not None:
                self.staged[name] = result[0]

        self.app.push_screen(RecordPicker(self._client, target.list_op, target.current_id), _stage)

    def action_go_back(self) -> None:
        self.app.pop_screen()
