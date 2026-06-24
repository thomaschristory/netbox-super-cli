from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import ListView, Static

from nsc.model.command_model import CommandModel, Operation, Resource, Tag
from nsc.tui.catalog import ResourceRef
from nsc.tui.screens.picker import ResourcePicker


def _model() -> CommandModel:
    def res(name: str) -> Resource:
        return Resource(
            name=name,
            list_op=Operation(operation_id=f"{name}_list", http_method="GET", path=f"/api/{name}/"),
        )

    tag = Tag(name="dcim", resources={"devices": res("devices"), "interfaces": res("interfaces")})
    return CommandModel(info_title="t", info_version="1", schema_hash="h", tags={"dcim": tag})


class _PickerApp(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.chosen: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("")

    async def on_mount(self) -> None:
        def _record(ref: ResourceRef) -> None:
            self.chosen = ref.resource_name

        await self.push_screen(ResourcePicker(_model()), _record)


async def test_picker_filters_and_selects() -> None:
    app = _PickerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i", "n", "t")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert app.chosen == "interfaces"


async def test_down_arrow_from_filter_focuses_the_list() -> None:
    app = _PickerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, ResourcePicker)
        assert app.focused is picker.query_one("#picker-filter")
        await pilot.press("down")
        await pilot.pause()
        assert app.focused is picker.query_one("#picker-list", ListView)


async def test_escape_on_root_picker_does_not_blank_out() -> None:
    app = _PickerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ResourcePicker)
        await pilot.press("escape")
        await pilot.pause()
        # still on the picker — escape must not reveal the blank base screen
        assert isinstance(app.screen, ResourcePicker)


async def test_picker_enter_with_no_match_does_not_dismiss() -> None:
    app = _PickerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("z", "z", "z", "z")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ResourcePicker)
    assert app.chosen is None
