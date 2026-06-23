"""The Textual application: screen stack, global keys, resource entry."""

from __future__ import annotations

from typing import Any, ClassVar

from textual.app import App
from textual.binding import BindingType

from nsc.model.command_model import CommandModel
from nsc.tui._bindings import textual_bindings
from nsc.tui.catalog import ResourceRef, list_resources
from nsc.tui.screens.list import ListScreen
from nsc.tui.screens.picker import ResourcePicker
from nsc.tui.widgets.help import HelpOverlay


class NscTuiApp(App[None]):
    BINDINGS: ClassVar[list[BindingType]] = textual_bindings("global")
    TITLE = "nsc"
    # Free up ctrl+p for our own resource picker; Textual binds it by default.
    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self, model: CommandModel, client: Any, *, initial_resource: str | None = None
    ) -> None:
        super().__init__()
        self._model = model
        self._client = client
        self._initial_resource = initial_resource

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

    def action_go_back(self) -> None:
        if len(self.screen_stack) > 1:
            self.pop_screen()


def run_tui(model: CommandModel, client: Any, *, initial_resource: str | None = None) -> None:
    NscTuiApp(model, client, initial_resource=initial_resource).run()
