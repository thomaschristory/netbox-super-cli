from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Input, Static, Tree

from nsc.model.command_model import CommandModel, Operation, Resource, Tag
from nsc.tui.catalog import ResourceRef
from nsc.tui.screens.picker import ResourcePicker


def _model() -> CommandModel:
    def res(name: str) -> Resource:
        return Resource(
            name=name,
            list_op=Operation(operation_id=f"{name}_list", http_method="GET", path=f"/api/{name}/"),
        )

    dcim = Tag(name="dcim", resources={"devices": res("devices"), "interfaces": res("interfaces")})
    ipam = Tag(name="ipam", resources={"prefixes": res("prefixes")})
    return CommandModel(
        info_title="t", info_version="1", schema_hash="h", tags={"dcim": dcim, "ipam": ipam}
    )


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


def _picker(app: _PickerApp) -> ResourcePicker:
    screen = app.screen
    assert isinstance(screen, ResourcePicker)
    return screen


async def test_tree_groups_by_tag_and_is_collapsed_initially() -> None:
    app = _PickerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = _picker(app).query_one("#picker-tree", Tree)
        assert [str(node.label) for node in tree.root.children] == ["dcim", "ipam"]
        assert all(not node.is_expanded for node in tree.root.children)


async def test_selecting_a_resource_leaf_dismisses_with_its_ref() -> None:
    app = _PickerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _picker(app)
        tree = screen.query_one("#picker-tree", Tree)
        leaf = tree.root.children[0].children[0]  # dcim → devices
        screen.on_tree_node_selected(Tree.NodeSelected(leaf))
        await pilot.pause()
    assert app.chosen == "devices"


async def test_picker_filters_and_selects() -> None:
    app = _PickerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i", "n", "t")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert app.chosen == "interfaces"


async def test_search_hides_non_matching_groups_and_expands_matches() -> None:
    app = _PickerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _picker(app)
        inp = screen.query_one("#picker-filter", Input)
        screen.on_input_changed(Input.Changed(inp, "pre"))  # matches ipam/prefixes only
        await pilot.pause()
        tree = screen.query_one("#picker-tree", Tree)
        assert [str(node.label) for node in tree.root.children] == ["ipam"]
        assert tree.root.children[0].is_expanded
        # clearing restores all groups, collapsed
        screen.on_input_changed(Input.Changed(inp, ""))
        await pilot.pause()
        assert [str(node.label) for node in tree.root.children] == ["dcim", "ipam"]
        assert all(not node.is_expanded for node in tree.root.children)


async def test_ctrl_e_expands_then_collapses_all_groups() -> None:
    app = _PickerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = _picker(app)
        tree = screen.query_one("#picker-tree", Tree)
        assert all(not node.is_expanded for node in tree.root.children)
        screen.action_toggle_all()
        await pilot.pause()
        assert all(node.is_expanded for node in tree.root.children)
        screen.action_toggle_all()
        await pilot.pause()
        assert all(not node.is_expanded for node in tree.root.children)


async def test_down_arrow_from_filter_focuses_the_tree() -> None:
    app = _PickerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = _picker(app)
        assert app.focused is picker.query_one("#picker-filter")
        await pilot.press("down")
        await pilot.pause()
        assert app.focused is picker.query_one("#picker-tree", Tree)


async def test_escape_on_root_picker_does_not_blank_out() -> None:
    app = _PickerApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ResourcePicker)
        await pilot.press("escape")
        await pilot.pause()
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
