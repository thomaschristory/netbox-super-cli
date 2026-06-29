"""DetailScreen — an inline-editable record view with relationship tabs.

The detail view doubles as the edit surface. Each editable field (those in the
update operation's request body) is a table row you edit in place: press
``e``/``enter`` to edit the highlighted field, ``enter`` again to validate the
value into a local staging buffer. ``s`` saves every staged change in a single
PATCH after a diff confirmation. Nothing reaches the network until that save.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Label, Tab, Tabs

from nsc.http.errors import NetBoxAPIError, NetBoxClientError
from nsc.model.command_model import CommandModel, Resource
from nsc.output.flatten import flatten
from nsc.tui._bindings import textual_bindings
from nsc.tui.errors import api_error_message
from nsc.tui.fk import is_fk_value, resolve_fk_target
from nsc.tui.forms import SET_NULL, WidgetSpec, compute_patch, diff_rows, field_to_widget
from nsc.tui.relations import RelatedView, related_views
from nsc.tui.view import detail_path, render_cell


@dataclass
class _FieldRow:
    name: str
    spec: WidgetSpec | None = None
    editable: bool = False


def _record_value(record: dict[str, Any], name: str) -> Any:
    value = record.get(name)
    if isinstance(value, dict) and "id" in value:
        return value["id"]
    return value


class DetailScreen(Screen[None]):
    BINDINGS: ClassVar[list[BindingType]] = textual_bindings("detail")

    def __init__(
        self,
        model: CommandModel,
        client: Any,
        tag: str,
        resource_name: str,
        resource: Resource,
        record: dict[str, Any],
    ) -> None:
        super().__init__()
        self._model = model
        self._client = client
        self._tag = tag
        self._resource_name = resource_name
        self._resource = resource
        self._record = record
        self._update_op = resource.update_op
        body = self._update_op.request_body if self._update_op is not None else None
        self._fields = body.fields if body is not None else {}
        self._sensitive = body.sensitive_paths if body is not None else ()
        self._specs: dict[str, WidgetSpec] = {}
        self._rows: list[_FieldRow] = []
        self.staged: dict[str, Any] = {}
        self._fk_labels: dict[str, str] = {}
        self._editing: str | None = None
        self._relations: list[RelatedView] = related_views(model, resource_name)
        self.title = f"{resource_name} #{record.get('id', '?')}"

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="fields")
        with Horizontal(id="edit-bar"):
            yield Label("", id="edit-bar-label")
        tabs = [Tab(v.resource_name, id=f"rel-{i}") for i, v in enumerate(self._relations)]
        yield Tabs(*tabs)
        yield Footer()

    @property
    def _tabs(self) -> Tabs:
        return self.query_one(Tabs)

    @property
    def _table(self) -> DataTable[str | Text]:
        return self.query_one("#fields", DataTable)

    def on_mount(self) -> None:
        self._build_rows()
        table = self._table
        table.cursor_type = "row"
        table.add_columns("field", "value")
        self._refresh_rows()
        self.query_one("#edit-bar", Horizontal).display = False
        table.focus()

    # --- row model -------------------------------------------------------
    def _build_rows(self) -> None:
        for name, shape in self._fields.items():
            spec = field_to_widget(name, shape, self._sensitive)
            self._specs[name] = spec
            self._rows.append(_FieldRow(name=name, spec=spec, editable=True))
        for key in flatten(self._record):
            if key.split(".", 1)[0] in self._fields:
                continue
            self._rows.append(_FieldRow(name=key))

    def _refresh_rows(self) -> None:
        flat = flatten(self._record)
        table = self._table
        cursor = table.cursor_row
        table.clear()
        patch = compute_patch(self._record, self.staged)
        for row in self._rows:
            dirty = row.name in patch
            label = f"* {row.name}" if dirty else row.name
            table.add_row(label, self._value_display(row, flat))
        if table.row_count:
            table.move_cursor(row=min(cursor, table.row_count - 1))

    def _value_display(self, row: _FieldRow, flat: dict[str, Any]) -> str | Text:
        if row.editable and row.name in self.staged:
            return self._staged_display(row)
        sensitive = row.spec is not None and row.spec.sensitive
        if row.editable:
            return self._editable_display(row.name, sensitive=sensitive)
        if isinstance(self._record.get(row.name), list):
            return self._render_list(row.name)
        value = flat.get(row.name)
        return "" if value is None else str(value)

    def _staged_display(self, row: _FieldRow) -> str:
        staged = self.staged[row.name]
        if staged is SET_NULL:
            return "(null)"
        # Never echo a just-typed secret; a picked FK stages a bare id, so show
        # its chosen label rather than the number.
        sensitive = row.spec is not None and row.spec.sensitive
        return "****" if sensitive and staged != "" else self._fk_labels.get(row.name, str(staged))

    def _editable_display(self, name: str, *, sensitive: bool) -> str | Text:
        value = self._record.get(name)
        if isinstance(value, dict):
            display = value.get("display")
            return str(display if display is not None else value.get("id", ""))
        if sensitive and value not in (None, ""):
            return "****"
        if isinstance(value, list):
            return self._render_list(name)
        return "" if value is None else str(value)

    def _render_list(self, name: str) -> str | Text:
        """Render a list-of-object field (tags, …) like the list table does.

        Routes through the same flatten/colour pipeline so the cell shows a
        comma-joined display string — colored when object colors are on — rather
        than a raw list-of-dicts repr.
        """
        object_colors = bool(getattr(self.app, "object_colors", False))
        rendered = flatten(self._record, columns=[name], with_colors=object_colors).get(name)
        return render_cell(rendered)

    # --- editing ---------------------------------------------------------
    def action_edit_field(self) -> None:
        if self._editing is not None:
            return
        row = self._current_row()
        if row is None:
            return
        if not row.editable or row.spec is None:
            self.notify(f"{row.name} is read-only.")
            return
        if self._is_fk(row.name, row.spec):
            self._edit_fk(row.name)
            return
        if row.spec.kind == "switch":
            current = self._staged_or_record(row.name)
            self.staged[row.name] = not bool(current)
            self._refresh_rows()
            return
        self._open_input(row.name, row.spec)

    def on_data_table_row_selected(self, _: DataTable.RowSelected) -> None:
        self.action_edit_field()

    def _current_row(self) -> _FieldRow | None:
        index = self._table.cursor_row
        if 0 <= index < len(self._rows):
            return self._rows[index]
        return None

    def _staged_or_record(self, name: str) -> Any:
        if name in self.staged:
            return self.staged[name]
        return _record_value(self._record, name)

    def _open_input(self, name: str, spec: WidgetSpec) -> None:
        self._editing = name
        bar = self.query_one("#edit-bar", Horizontal)
        bar.display = True
        hint = f" ({'/'.join(spec.choices)})" if spec.kind == "select" else ""
        self.query_one("#edit-bar-label", Label).update(f"{name}{hint}:")
        current = self._staged_or_record(name)
        text = "" if current in (None, SET_NULL) else str(current)
        editor = Input(value=text, password=spec.sensitive, id="editor")
        bar.mount(editor)
        editor.focus()

    def _edit_fk(self, name: str) -> None:
        target = resolve_fk_target(name, self._record.get(name), self._model)
        if target.kind == "raw_id" or target.list_op is None:
            spec = self._specs[name]
            self._open_input(name, spec)
            return
        from nsc.tui.screens.record_picker import RecordPicker  # noqa: PLC0415

        def _stage(result: tuple[int, str] | None) -> None:
            if result is not None:
                self.staged[name] = result[0]
                self._fk_labels[name] = result[1]
                self._refresh_rows()

        self.app.push_screen(RecordPicker(self._client, target.list_op, target.current_id), _stage)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "editor" or self._editing is None:
            return
        name = self._editing
        spec = self._specs[name]
        value = self._coerce(name, spec, event.value)
        if value is _INVALID:
            self.notify(f"Invalid value for {name}.")
            return
        self.staged[name] = value
        self._close_input()
        self._refresh_rows()

    def _coerce(self, name: str, spec: WidgetSpec, raw: str) -> Any:
        if raw == "":
            return SET_NULL if spec.nullable else ""
        if spec.kind == "select":
            return raw if raw in spec.choices else _INVALID
        if spec.kind == "number" or self._is_fk(name, spec):
            try:
                return float(raw) if spec.is_float else int(raw)
            except ValueError:
                return _INVALID
        return raw

    def _close_input(self) -> None:
        for editor in self.query("#editor"):
            editor.remove()
        self.query_one("#edit-bar", Horizontal).display = False
        self._editing = None
        self._table.focus()

    def _is_fk(self, name: str, spec: WidgetSpec) -> bool:
        # Writable FK fields type as oneOf[int, brief] -> UNKNOWN -> `text`, so a
        # `number`-only gate would miss real relations. Key off the record's
        # nested object instead; exclude enum/bool/secret/float.
        if spec.kind in ("select", "switch", "masked") or spec.is_float:
            return False
        return name.endswith("_id") or is_fk_value(self._record.get(name))

    # --- save ------------------------------------------------------------
    def action_save_all(self) -> None:
        if self._editing is not None or self._update_op is None:
            return
        patch = compute_patch(self._record, self.staged)
        if not patch:
            self.notify("No changes to save.")
            return
        from nsc.tui.widgets.diff import DiffModal  # noqa: PLC0415

        def _on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self._apply_patch(patch)

        rows = diff_rows(self._record, patch, self._sensitive, self._fk_labels)
        self.app.push_screen(DiffModal(rows), _on_confirm)

    def _apply_patch(self, patch: dict[str, Any]) -> None:
        assert self._update_op is not None
        try:
            self._client.patch(
                detail_path(self._update_op.path, self._record.get("id")),
                json=patch,
                operation_id=self._update_op.operation_id,
                sensitive_paths=self._sensitive,
            )
        except (NetBoxAPIError, NetBoxClientError) as exc:
            self.notify(api_error_message(exc), severity="error", timeout=8)
            return
        self._record.update(patch)
        self.staged.clear()
        self._refresh_rows()
        self.notify("Saved.")

    # --- navigation ------------------------------------------------------
    def action_go_back(self) -> None:
        if self._editing is not None:
            self._close_input()
            return
        if not compute_patch(self._record, self.staged):
            self.app.pop_screen()
            return
        from nsc.tui.widgets.confirm import ConfirmModal  # noqa: PLC0415

        def _on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self.app.pop_screen()

        self.app.push_screen(ConfirmModal("Discard unsaved changes?"), _on_confirm)

    def action_drill_relation(self) -> None:
        if self._editing is not None or not self._relations:
            return
        active = self._tabs.active
        if not active:
            return
        index = int(active.removeprefix("rel-"))
        view = self._relations[index]
        record_id = self._record.get("id")
        if record_id is None:
            return
        from nsc.tui.screens.list import ListScreen  # noqa: PLC0415

        self.app.push_screen(
            ListScreen(
                self._model,
                self._client,
                view.tag,
                view.resource_name,
                view.list_op,
                base_filters={view.filter_param: str(record_id)},
            )
        )

    def action_next_tab(self) -> None:
        if self._editing is None:
            self._tabs.action_next_tab()

    def action_prev_tab(self) -> None:
        if self._editing is None:
            self._tabs.action_previous_tab()

    def _detail_path(self) -> str | None:
        record_id = self._record.get("id")
        if record_id is None:
            return None
        op = self._resource.get_op or self._resource.list_op
        if op is None:
            return None
        return detail_path(op.path, record_id)

    def action_delete_record(self) -> None:
        if self._editing is not None:
            return
        delete_op = self._resource.delete_op
        if delete_op is None:
            return
        path = self._detail_path()
        if path is None:
            return
        from nsc.tui.widgets.confirm import ConfirmModal  # noqa: PLC0415

        message = f"Delete {self._resource_name} #{self._record.get('id')}?"

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                self._client.delete(path, operation_id=delete_op.operation_id)
            except (NetBoxAPIError, NetBoxClientError) as exc:
                self.notify(api_error_message(exc), severity="error", timeout=8)
                return
            self.app.pop_screen()
            self._reload_underlying_list()

        self.app.push_screen(ConfirmModal(message), _on_confirm)

    def _reload_underlying_list(self) -> None:
        from nsc.tui.screens.list import ListScreen  # noqa: PLC0415

        if isinstance(self.app.screen, ListScreen):
            self.app.screen.reload()


class _Invalid:
    """Sentinel returned by coercion when a typed value cannot be accepted."""


_INVALID = _Invalid()
