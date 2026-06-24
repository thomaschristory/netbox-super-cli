"""BulkEditForm — choose *which* fields to set and one value each, for N records.

Mirrors :class:`EditForm`'s widget composition (Phase-2 ``forms`` layer) but adds
a per-field *include* toggle. A field contributes to the bulk ``set`` only while
its include toggle is on, so a widget showing a value is ignored unless the user
opts the field in. Nothing reaches the network until an explicit preview/apply
(handled by a later phase).
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
from nsc.tui.forms import SET_NULL, WidgetSpec, field_to_widget


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


class BulkEditForm(Screen[None]):
    BINDINGS: ClassVar[list[BindingType]] = textual_bindings("edit")

    def __init__(
        self,
        model: CommandModel,
        client: _Client,
        tag: str,
        resource_name: str,
        update_op: Operation,
        selected_records: list[dict[str, Any]],
    ) -> None:
        super().__init__()
        self._model = model
        self._client = client
        self._tag = tag
        self._resource_name = resource_name
        self._op = update_op
        self._selected = selected_records
        self._specs: dict[str, WidgetSpec] = {}
        self._values: dict[str, Any] = {}
        self._included: set[str] = set()
        self.title = f"Bulk edit {len(selected_records)} {resource_name}"

    @property
    def bulk_set(self) -> dict[str, Any]:
        return {name: self._values[name] for name in self._included if name in self._values}

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="bulk-form-body"):
            body = self._op.request_body
            fields = body.fields if body is not None else {}
            sensitive = body.sensitive_paths if body is not None else ()
            for name, field in fields.items():
                spec = field_to_widget(name, field, sensitive)
                self._specs[name] = spec
                yield from self._compose_field(name, spec)
            yield Button("Preview", id="preview", classes="bulk-preview")
        yield Footer()

    def _compose_field(self, name: str, spec: WidgetSpec) -> ComposeResult:
        with Horizontal(classes="bulk-field"):
            yield Switch(value=False, id=f"include-{name}", classes="bulk-include")
            yield Label(name, classes="bulk-label")
            yield from self._compose_widget(name, spec)
            if spec.nullable:
                yield Button("∅", id=f"setnull-{name}", classes="bulk-setnull")

    def _compose_widget(self, name: str, spec: WidgetSpec) -> ComposeResult:
        if spec.kind == "select":
            options = [(choice, choice) for choice in spec.choices]
            yield Select(options, value=Select.NULL, id=f"field-{name}", allow_blank=True)
            return
        if spec.kind == "switch":
            yield Switch(value=False, id=f"field-{name}")
            return
        yield Input(value="", password=spec.sensitive, id=f"field-{name}")

    @staticmethod
    def _strip(ident: str | None, prefix: str) -> str | None:
        if ident is None or not ident.startswith(prefix):
            return None
        return ident.removeprefix(prefix)

    def on_input_changed(self, event: Input.Changed) -> None:
        name = self._strip(event.input.id, "field-")
        if name is None:
            return
        self._values[name] = self._coerce_input(name, event.value)

    def _coerce_input(self, name: str, raw: str) -> Any:
        spec = self._specs.get(name)
        if spec is None or spec.kind != "number":
            return raw
        if raw == "":
            return None
        try:
            return float(raw) if spec.is_float else int(raw)
        except ValueError:
            return raw

    def on_switch_changed(self, event: Switch.Changed) -> None:
        include = self._strip(event.switch.id, "include-")
        if include is not None:
            if event.value:
                self._included.add(include)
            else:
                self._included.discard(include)
            return
        name = self._strip(event.switch.id, "field-")
        if name is not None:
            self._values[name] = event.value

    def on_select_changed(self, event: Select.Changed) -> None:
        name = self._strip(event.select.id, "field-")
        if name is None:
            return
        self._values[name] = None if event.value is Select.NULL else event.value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        ident = event.button.id
        if ident is None:
            return
        if ident == "preview":
            self.action_preview()
            return
        name = self._strip(ident, "setnull-")
        if name is not None:
            self._values[name] = SET_NULL

    def action_preview(self) -> None:
        from nsc.tui.bulk import bulk_diff  # noqa: PLC0415
        from nsc.tui.widgets.bulk_diff import BulkDiffModal  # noqa: PLC0415

        body = self._op.request_body
        sensitive = body.sensitive_paths if body is not None else ()
        changes = bulk_diff(self._selected, self.bulk_set, sensitive)
        self.app.push_screen(BulkDiffModal(changes))
