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

SavedSearchMap = dict[str, dict[str, dict[str, dict[str, str]]]]


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
        object_colors: bool = False,
        saved_searches: SavedSearchMap | None = None,
        save_search: Callable[[str, str, str, dict[str, str]], None] | None = None,
        delete_search: Callable[[str, str, str], None] | None = None,
        saved_filter_store: Any | None = None,
    ) -> None:
        super().__init__()
        self._model = model
        self._client = client
        self._initial_resource = initial_resource
        self._save_columns = save_columns
        self._column_prefs = column_prefs or {}
        self.object_colors = object_colors
        self._saved_searches: SavedSearchMap = saved_searches or {}
        self._save_search = save_search
        self._delete_search = delete_search
        self._saved_filter_store = saved_filter_store
        if saved_filter_store is not None and getattr(saved_filter_store, "on_error", None) is None:
            saved_filter_store.on_error = self._notify_saved_filter_issue
        from nsc.savedfilters.custom_fields import CustomFieldResolver  # noqa: PLC0415
        from nsc.savedfilters.tags import TagsResolver  # noqa: PLC0415

        self._custom_field_resolver = CustomFieldResolver(client)
        self._tags_resolver = TagsResolver(client)

    def custom_field_defs_for(self, tag: str, resource: str) -> dict[str, Any] | None:
        """Custom-field definitions for a resource (read by list/forms), or None."""
        return self._custom_field_resolver.resolve(self._list_path(tag, resource))

    def available_tags(self) -> Any | None:
        """All NetBox tags (read by the tag-picker widget), or None if unavailable."""
        return self._tags_resolver.resolve()

    def columns_for(self, tag: str, resource: str) -> list[str] | None:
        """Saved visible columns for a resource, if any (read by ListScreen)."""
        return self._column_prefs.get(tag, {}).get(resource)

    def save_columns(self, tag: str, resource: str, columns: list[str]) -> None:
        # Update the in-memory map too, so re-opening the list this session
        # reflects the choice without a relaunch.
        self._column_prefs.setdefault(tag, {})[resource] = list(columns)
        if self._save_columns is not None:
            self._save_columns(tag, resource, columns)

    def _list_path(self, tag: str, resource: str) -> str:
        """The NetBox list URL for a resource, used to resolve its object type."""
        try:
            list_op = self._model.tags[tag].resources[resource].list_op
        except KeyError:
            return ""
        return list_op.path if list_op is not None else ""

    def _notify_saved_filter_issue(self, message: str) -> None:
        self.notify(message, severity="warning")

    def saved_searches_for(self, tag: str, resource: str) -> dict[str, dict[str, str]]:
        """Named saved filter sets for a resource (read by FilterScreen).

        Backed by NetBox's native saved filters when a store is wired (so the web
        UI's filters appear here too); otherwise the in-memory config map.
        """
        if self._saved_filter_store is not None:
            result: dict[str, dict[str, str]] = self._saved_filter_store.list(
                self._list_path(tag, resource), tag, resource
            )
            return result
        return self._saved_searches.get(tag, {}).get(resource, {})

    def save_search(self, tag: str, resource: str, name: str, params: dict[str, str]) -> None:
        if self._saved_filter_store is not None:
            path = self._list_path(tag, resource)
            self._saved_filter_store.save(path, tag, resource, name, params)
            return
        # Update the in-memory map too so the picker reflects the new entry
        # immediately, without a relaunch.
        self._saved_searches.setdefault(tag, {}).setdefault(resource, {})[name] = dict(params)
        if self._save_search is not None:
            self._save_search(tag, resource, name, params)

    def delete_search(self, tag: str, resource: str, name: str) -> None:
        if self._saved_filter_store is not None:
            self._saved_filter_store.delete(self._list_path(tag, resource), tag, resource, name)
            return
        self._saved_searches.get(tag, {}).get(resource, {}).pop(name, None)
        if self._delete_search is not None:
            self._delete_search(tag, resource, name)

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
    object_colors: bool = False,
    saved_searches: SavedSearchMap | None = None,
    save_search: Callable[[str, str, str, dict[str, str]], None] | None = None,
    delete_search: Callable[[str, str, str], None] | None = None,
    saved_filter_store: Any | None = None,
) -> None:
    NscTuiApp(
        model,
        client,
        initial_resource=initial_resource,
        save_columns=save_columns,
        column_prefs=column_prefs,
        object_colors=object_colors,
        saved_searches=saved_searches,
        save_search=save_search,
        delete_search=delete_search,
        saved_filter_store=saved_filter_store,
    ).run()
