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
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    Select,
    SelectionList,
    Switch,
)
from textual.widgets.selection_list import Selection

from nsc.model.command_model import CommandModel, Operation
from nsc.savedfilters.custom_fields import CustomFieldDef
from nsc.savedfilters.tags import TagDef
from nsc.tui._bindings import textual_bindings
from nsc.tui.bulk import RecordChange, shared_values
from nsc.tui.fk import is_fk_value, resolve_fk_target
from nsc.tui.forms import (
    SET_NULL,
    WidgetSpec,
    decode_field_id,
    encode_field_id,
    expand_custom_fields,
    field_to_widget,
    fk_display,
    flatten_custom_fields,
    nest_custom_fields,
    tags_payload,
    tags_widget_spec,
)
from nsc.tui.view import detail_path

# Sentinel: a picker FK opted in with neither a pick nor a shared value
# contributes nothing, so it never nulls the relation.
_NO_SEED = object()


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
        custom_field_defs: dict[str, CustomFieldDef] | None = None,
        available_tags: tuple[TagDef, ...] | None = None,
    ) -> None:
        super().__init__()
        self._model = model
        self._client = client
        self._tag = tag
        self._resource_name = resource_name
        self._op = update_op
        self._selected = selected_records
        self._cf_defs = custom_field_defs
        self._tags = available_tags
        self._specs: dict[str, WidgetSpec] = {}
        self._values: dict[str, Any] = {}
        self._included: set[str] = set()
        self._fk_kinds: dict[str, str] = {}
        self._fk_labels: dict[str, str] = {}
        body = update_op.request_body
        field_names = list(body.fields) if body is not None else []
        # Custom fields are staged under flattened ``custom_fields.<name>`` keys,
        # so seed their shared value from flattened records too — otherwise a
        # widget defaults (e.g. a boolean to False) and opting it in unchanged
        # would silently overwrite the records' shared value.
        cf_names = [f"custom_fields.{cf.name}" for cf in (custom_field_defs or {}).values()]
        flattened_records = [flatten_custom_fields(record) for record in selected_records]
        # Shared current value per field, to seed the widgets (does NOT opt the
        # field in — the include toggle still gates what gets set).
        self._shared = shared_values(flattened_records, field_names + cf_names)
        self.progress_total = 0
        self.progress_done = 0
        self.title = f"Bulk edit {len(selected_records)} {resource_name}"

    @property
    def bulk_set(self) -> dict[str, Any]:
        return {name: self._values[name] for name in self._included if name in self._values}

    def _field_labels(self) -> dict[str, str]:
        """Human labels for fields that carry one (custom fields), for the diff."""
        return {name: spec.label for name, spec in self._specs.items() if spec.label}

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="bulk-form-body"):
            body = self._op.request_body
            fields = body.fields if body is not None else {}
            sensitive = body.sensitive_paths if body is not None else ()
            for name, field in fields.items():
                for spec in self._specs_for(name, field, sensitive):
                    self._specs[spec.name] = spec
                    yield from self._compose_field(spec.name, spec)
            yield Button("Preview", id="preview", classes="bulk-preview")
            progress = ProgressBar(id="bulk-progress", show_eta=False)
            progress.display = False
            yield progress
        yield Footer()

    def _specs_for(self, name: str, field: Any, sensitive: tuple[str, ...]) -> list[WidgetSpec]:
        """Widget spec(s) for a body field — expanding custom_fields and tags.

        Each expanded custom field gets its own include toggle, so users opt in
        only the fields they intend to set across the selection.
        """
        if name == "custom_fields" and self._cf_defs:
            return expand_custom_fields(self._cf_defs)
        if name == "tags" and self._tags is not None:
            return [tags_widget_spec(name, self._tags, ())]
        return [field_to_widget(name, field, sensitive)]

    def _compose_field(self, name: str, spec: WidgetSpec) -> ComposeResult:
        with Horizontal(classes="bulk-field"):
            yield Switch(value=False, id=f"include-{encode_field_id(name)}", classes="bulk-include")
            yield Label(spec.label or name, classes="bulk-label")
            yield from self._compose_widget(name, spec)
            if spec.nullable and spec.kind != "multi_select":
                yield Button("∅", id=f"setnull-{encode_field_id(name)}", classes="bulk-setnull")

    def _is_fk(self, name: str, spec: WidgetSpec) -> bool:
        if spec.kind in ("select", "switch", "masked") or spec.is_float:
            return False
        return name.endswith("_id") or any(
            is_fk_value(record.get(name)) for record in self._selected
        )

    def _fk_nested_value(self, name: str) -> Any:
        """A representative nested FK object across the selection, for resolution."""
        for record in self._selected:
            value = record.get(name)
            if is_fk_value(value):
                return value
        return None

    def _fk_seed_label(self, name: str) -> str:
        shared_id = self._shared.get(name)
        if shared_id is None:
            return ""
        for record in self._selected:
            value = record.get(name)
            if isinstance(value, dict) and value.get("id") == shared_id:
                return fk_display(value)
        return str(shared_id)

    def _compose_fk(self, name: str) -> ComposeResult:
        target = resolve_fk_target(
            name,
            self._fk_nested_value(name),
            self._model,
            context_tag=self._tag,
            context_resource=self._resource_name,
        )
        self._fk_kinds[name] = target.kind
        shared_id = self._shared.get(name)
        if target.kind == "raw_id":
            text = "" if shared_id is None else str(shared_id)
            yield Input(value=text, id=f"field-{encode_field_id(name)}")
            if target.hint:
                yield Label(target.hint, classes="bulk-fk-hint")
            return
        yield Button(
            f"{name}: {self._fk_seed_label(name)}",
            id=f"fk-{encode_field_id(name)}",
            classes="bulk-fk",
        )

    def _compose_widget(self, name: str, spec: WidgetSpec) -> ComposeResult:
        wid = f"field-{encode_field_id(name)}"
        if spec.kind == "multi_select":
            # Tags seed via spec.selected; a custom-field multiselect seeds its
            # shared current list so opting it in unchanged isn't a destructive
            # clear (tags are intentionally left blank — they have their own flow).
            selected = set(spec.selected)
            if not selected and name != "tags":
                shared = self._shared.get(name)
                if isinstance(shared, list):
                    selected = {str(v) for v in shared}
            yield SelectionList[str](
                *(Selection(label, val, val in selected) for label, val in spec.options),
                id=wid,
                classes="bulk-multiselect",
            )
            return
        if self._is_fk(name, spec):
            yield from self._compose_fk(name)
            return
        shared = self._shared.get(name)
        if spec.kind == "select":
            options = [(choice, choice) for choice in spec.choices]
            value = shared if shared in spec.choices else Select.NULL
            yield Select(options, value=value, id=wid, allow_blank=True)
            return
        if spec.kind == "switch":
            yield Switch(value=bool(shared), id=wid)
            return
        text = "" if shared is None else str(shared)
        yield Input(value=text, password=spec.sensitive, id=wid)

    @staticmethod
    def _strip(ident: str | None, prefix: str) -> str | None:
        if ident is None or not ident.startswith(prefix):
            return None
        return decode_field_id(ident.removeprefix(prefix))

    def on_input_changed(self, event: Input.Changed) -> None:
        name = self._strip(event.input.id, "field-")
        if name is None:
            return
        self._values[name] = self._coerce_input(name, event.value)

    def _coerce_input(self, name: str, raw: str) -> Any:
        spec = self._specs.get(name)
        numeric = (spec is not None and spec.kind == "number") or self._fk_kinds.get(
            name
        ) == "raw_id"
        if not numeric:
            return raw
        if raw == "":
            return None
        try:
            return float(raw) if spec is not None and spec.is_float else int(raw)
        except ValueError:
            return raw

    def on_switch_changed(self, event: Switch.Changed) -> None:
        include = self._strip(event.switch.id, "include-")
        if include is not None:
            if event.value:
                self._included.add(include)
                if include not in self._values:
                    seed = self._read_widget_value(include)
                    if seed is not _NO_SEED:
                        self._values[include] = seed
            else:
                self._included.discard(include)
            return
        name = self._strip(event.switch.id, "field-")
        if name is not None:
            self._values[name] = event.value

    def _read_widget_value(self, name: str) -> Any:
        spec = self._specs.get(name)
        wid = f"#field-{encode_field_id(name)}"
        if self._fk_kinds.get(name) == "picker":
            shared_id = self._shared.get(name)
            return shared_id if shared_id is not None else _NO_SEED
        if spec is not None and spec.kind == "multi_select":
            return self._multiselect_value(name, self.query_one(wid, SelectionList).selected)
        if spec is not None and spec.kind == "select":
            value = self.query_one(wid, Select).value
            # A blank select (no/unresolved choices, or a current value not in the
            # options) must not seed a null on opt-in — that would silently clear a
            # field the user never edited. Only the explicit ∅ button nulls.
            return _NO_SEED if value is Select.NULL else value
        if spec is not None and spec.kind == "switch":
            return self.query_one(wid, Switch).value
        return self._coerce_input(name, self.query_one(wid, Input).value)

    def _multiselect_value(self, name: str, selected: list[Any]) -> Any:
        slugs = tuple(str(v) for v in selected)
        if name == "tags":
            return tags_payload(slugs, self._tags or ())
        return list(slugs)

    def on_select_changed(self, event: Select.Changed) -> None:
        name = self._strip(event.select.id, "field-")
        if name is None:
            return
        # A blank select on a field the user hasn't opted in must not stage a null
        # (which would clear the field on apply). Only the explicit ∅ button nulls.
        if event.value is Select.NULL and name not in self._included:
            return
        self._values[name] = None if event.value is Select.NULL else event.value

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged[str]) -> None:
        name = self._strip(event.selection_list.id, "field-")
        if name is None:
            return
        self._values[name] = self._multiselect_value(name, event.selection_list.selected)

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
            # Drop any picked label so the diff can't show a name while the
            # patch nulls the relation.
            self._fk_labels.pop(name, None)
            return
        fk = self._strip(ident, "fk-")
        if fk is not None:
            self._open_picker(fk)

    def _open_picker(self, name: str) -> None:
        target = resolve_fk_target(
            name,
            self._fk_nested_value(name),
            self._model,
            context_tag=self._tag,
            context_resource=self._resource_name,
        )
        if target.list_op is None:
            return
        from nsc.tui.screens.record_picker import RecordPicker  # noqa: PLC0415

        def _stage(result: tuple[int, str] | None) -> None:
            if result is not None:
                self._values[name] = result[0]
                self._fk_labels[name] = result[1]
                self.query_one(
                    f"#fk-{encode_field_id(name)}", Button
                ).label = f"{name}: {result[1]}"

        self.app.push_screen(RecordPicker(self._client, target.list_op, target.current_id), _stage)

    def action_preview(self) -> None:
        from nsc.tui.bulk import bulk_diff  # noqa: PLC0415
        from nsc.tui.widgets.bulk_diff import BulkDiffModal  # noqa: PLC0415

        body = self._op.request_body
        sensitive = body.sensitive_paths if body is not None else ()
        # Flatten custom_fields so each chosen custom_fields.<name> diffs per record.
        flattened = [flatten_custom_fields(record) for record in self._selected]
        changes = bulk_diff(
            flattened, self.bulk_set, sensitive, self._fk_labels, self._field_labels()
        )

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
                json=nest_custom_fields(change.patch),
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
