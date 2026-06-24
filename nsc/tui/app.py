"""The Textual application: screen stack, global keys, resource entry."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from textual.app import App
from textual.binding import BindingType

from nsc.model.command_model import CommandModel
from nsc.tui._bindings import textual_bindings
from nsc.tui.catalog import ResourceRef, list_resources
from nsc.tui.nav import can_go_back
from nsc.tui.screens.list import ListScreen
from nsc.tui.screens.picker import ResourcePicker
from nsc.tui.widgets.help import HelpOverlay


class NscTuiApp(App[None]):
    BINDINGS: ClassVar[list[BindingType]] = textual_bindings("global")
    CSS_PATH: ClassVar[str] = "styles.tcss"
    TITLE = "nsc"
    # Free up ctrl+p for our own resource picker; Textual binds it by default.
    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        model: CommandModel,
        client: Any,
        *,
        initial_resource: str | None = None,
        save_columns: Callable[[str, str, list[str]], None] | None = None,
        column_prefs: dict[str, dict[str, list[str]]] | None = None,
    ) -> None:
        super().__init__()
        self._model = model
        self._client = client
        self._initial_resource = initial_resource
        self._save_columns = save_columns
        self._column_prefs = column_prefs or {}

    def columns_for(self, tag: str, resource: str) -> list[str] | None:
        """Saved visible columns for a resource, if any (read by ListScreen)."""
        return self._column_prefs.get(tag, {}).get(resource)

    def save_columns(self, tag: str, resource: str, columns: list[str]) -> None:
        # Update the in-memory map too, so re-opening the list this session
        # reflects the choice without a relaunch.
        self._column_prefs.setdefault(tag, {})[resource] = list(columns)
        if self._save_columns is not None:
            self._save_columns(tag, resource, columns)

    def on_mount(self) -> None:
        ref = self._resolve_initial()
        if ref is None:
            self.push_screen(ResourcePicker(self._model), self._open_ref)
        else:
            self._open_ref(ref)

    def _resolve_initial(self) -> ResourceRef | None:
        if self._initial_resource is None:
            return None
        for ref in list_resources(self._model):
            if ref.resource_name == self._initial_resource:
                return ref
        return None

    def _open_ref(self, ref: ResourceRef | None) -> None:
        if ref is None:
            return
        self.push_screen(
            ListScreen(self._model, self._client, ref.tag, ref.resource_name, ref.list_op)
        )

    def action_quit_tui(self) -> None:
        self.exit()

    async def action_request_help(self) -> None:
        await self.push_screen(HelpOverlay())

    def action_open_palette(self) -> None:
        self.push_screen(ResourcePicker(self._model), self._open_ref)

    def action_open_search(self) -> None:
        from nsc.tui.screens.global_search import GlobalSearchScreen  # noqa: PLC0415

        self.push_screen(GlobalSearchScreen(self._model, self._client))

    def action_go_back(self) -> None:
        if can_go_back(self):
            self.pop_screen()


def run_tui(
    model: CommandModel,
    client: Any,
    *,
    initial_resource: str | None = None,
    save_columns: Callable[[str, str, list[str]], None] | None = None,
    column_prefs: dict[str, dict[str, list[str]]] | None = None,
) -> None:
    NscTuiApp(
        model,
        client,
        initial_resource=initial_resource,
        save_columns=save_columns,
        column_prefs=column_prefs,
    ).run()
