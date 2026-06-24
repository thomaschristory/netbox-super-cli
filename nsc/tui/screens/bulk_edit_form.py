"""BulkEditForm — choose *which* fields to set and one value each, for N records.

Mirrors :class:`EditForm`'s widget composition (Phase-2 ``forms`` layer) but adds
a per-field *include* toggle. A field contributes to the bulk ``set`` only while
its include toggle is on, so a widget showing a value is ignored unless the user
opts the field in. Nothing reaches the network until an explicit preview/apply
(handled by a later phase).
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar, Protocol

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, ProgressBar, Select, Switch

from nsc.model.command_model import CommandModel, Operation
from nsc.tui._bindings import textual_bindings
from nsc.tui.bulk import RecordChange, shared_values
from nsc.tui.forms import SET_NULL, WidgetSpec, field_to_widget
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


class BulkEditForm(Screen[None]):
    BINDINGS: ClassVar[list[BindingType]] = textual_bindings("bulk")

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
        body = update_op.request_body
        field_names = list(body.fields) if body is not None else []
        # Shared current value per field, to seed the widgets (does NOT opt the
        # field in — the include toggle still gates what gets set).
        self._shared = shared_values(selected_records, field_names)
        self.progress_total = 0
        self.progress_done = 0
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
            progress = ProgressBar(id="bulk-progress", show_eta=False)
            progress.display = False
            yield progress
        yield Footer()

    def _compose_field(self, name: str, spec: WidgetSpec) -> ComposeResult:
        with Horizontal(classes="bulk-field"):
            yield Switch(value=False, id=f"include-{name}", classes="bulk-include")
            yield Label(name, classes="bulk-label")
            yield from self._compose_widget(name, spec)
            if spec.nullable:
                yield Button("∅", id=f"setnull-{name}", classes="bulk-setnull")

    def _compose_widget(self, name: str, spec: WidgetSpec) -> ComposeResult:
        shared = self._shared.get(name)
        if spec.kind == "select":
            options = [(choice, choice) for choice in spec.choices]
            value = shared if shared in spec.choices else Select.NULL
            yield Select(options, value=value, id=f"field-{name}", allow_blank=True)
            return
        if spec.kind == "switch":
            yield Switch(value=bool(shared), id=f"field-{name}")
            return
        text = "" if shared is None else str(shared)
        yield Input(value=text, password=spec.sensitive, id=f"field-{name}")

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
                self._values.setdefault(include, self._read_widget_value(include))
            else:
                self._included.discard(include)
            return
        name = self._strip(event.switch.id, "field-")
        if name is not None:
            self._values[name] = event.value

    def _read_widget_value(self, name: str) -> Any:
        spec = self._specs.get(name)
        if spec is not None and spec.kind == "select":
            value = self.query_one(f"#field-{name}", Select).value
            return None if value is Select.NULL else value
        if spec is not None and spec.kind == "switch":
            return self.query_one(f"#field-{name}", Switch).value
        return self._coerce_input(name, self.query_one(f"#field-{name}", Input).value)

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

        def _on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self._apply_bulk(changes, sensitive)

        self.app.push_screen(BulkDiffModal(changes), _on_confirm)

    def _apply_bulk(self, changes: list[RecordChange], sensitive_paths: tuple[str, ...]) -> None:
        self.progress_total = sum(1 for change in changes if change.patch)
        self.progress_done = 0
        bar = self.query_one("#bulk-progress", ProgressBar)
        bar.display = True
        bar.update(total=max(self.progress_total, 1), progress=0)
        self.run_worker(self._run_bulk(changes, sensitive_paths), exclusive=True)

    async def _run_bulk(
        self, changes: list[RecordChange], sensitive_paths: tuple[str, ...]
    ) -> None:
        from nsc.tui.bulk import apply_bulk  # noqa: PLC0415
        from nsc.tui.widgets.bulk_summary import BulkSummaryModal  # noqa: PLC0415

        def _patch(change: RecordChange) -> None:
            self._client.patch(
                detail_path(self._op.path, change.record_id),
                json=change.patch,
                operation_id=self._op.operation_id,
                sensitive_paths=sensitive_paths,
            )

        def _advance(index: int, total: int) -> None:
            if changes[index - 1].patch:
                self.progress_done += 1
                self.query_one("#bulk-progress", ProgressBar).advance(1)

        def _on_progress(index: int, total: int) -> None:
            # apply_bulk runs in a worker thread; bump the bar on the UI thread.
            self.app.call_from_thread(_advance, index, total)

        result = await asyncio.to_thread(apply_bulk, changes, _patch, _on_progress)
        self.app.push_screen(BulkSummaryModal(result), self._on_summary_dismissed)

    def _on_summary_dismissed(self, _: None) -> None:
        self.dismiss()

    def action_go_back(self) -> None:
        if not self.bulk_set:
            self.dismiss()
            return
        from nsc.tui.widgets.confirm import ConfirmModal  # noqa: PLC0415

        def _on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self.dismiss()

        self.app.push_screen(ConfirmModal("Discard staged bulk changes?"), _on_confirm)
