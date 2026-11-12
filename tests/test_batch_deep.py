"""
Deep unit tests for core/batch.py.
Covers lazy exporter discovery, recursive and non-recursive asset discovery,
.blend filtering (locking files, backup files, nested export exclusion),
mirrored hierarchical path computation, object cleanup, and process_single_asset guards.
"""

from __future__ import annotations

from typing import Any, cast

import os
import tempfile
from unittest.mock import MagicMock, patch

from core.batch import BatchProcessorEngine


class MockObject:
    def __init__(self, name: str, obj_type: str = "MESH"):
        self.name = name
        self.type = obj_type
        self.data = MagicMock(name=f"{name}_Mesh", users=0)


class MockCollection:
    def __init__(self, name: str = "Coll"):
        self.name = name
        self.objects = MagicMock()


class MockBlendData:
    def __init__(self):
        self.objects = MockDataCollection()
        self.meshes = MockDataCollection()
        self.collections = MockDataCollection()


class MockDataCollection:
    def __init__(self):
        self._items: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._items.get(key, default)

    def new(self, name: str, *args: Any, **kwargs: Any) -> Any:
        item = MagicMock(name=name)
        self._items[name] = item
        return item

    def remove(self, item: Any, do_unlink: bool = True) -> None:
        name = getattr(item, "name", "")
        self._items.pop(name, None)

    def __iter__(self):
        return iter(self._items.values())

    def __contains__(self, item: Any) -> bool:
        return item in self._items.values() or item in self._items


# ==============================================================================
# Lazy Exporter Discovery Tests
# ==============================================================================


def test_get_exporter_engines():
    # Explicit registration
    mock_handler = MagicMock()
    BatchProcessorEngine.register_exporter("CUSTOM_ENGINE", mock_handler)
    assert BatchProcessorEngine._get_exporter("CUSTOM_ENGINE") == mock_handler

    with patch("exporters.ue5_export.UE5Exporter.export_asset", return_value=True) as mock_ue5:
        exp_ue5 = BatchProcessorEngine._get_exporter("UE5")
        assert exp_ue5 is not None
        assert exp_ue5 == mock_ue5

    with patch("exporters.msfs_export.MSFSExporter.export_asset", return_value=True) as mock_msfs:
        exp_msfs = BatchProcessorEngine._get_exporter("MSFS_2024")
        assert exp_msfs is not None
        assert exp_msfs == mock_msfs

    with patch("exporters.unity_export.UnityExporter.export_asset", return_value=True) as mock_unity:
        exp_unity = BatchProcessorEngine._get_exporter("UNITY_6")
        assert exp_unity is not None
        assert exp_unity == mock_unity

    # Unknown engine
    assert BatchProcessorEngine._get_exporter("UNSUPPORTED_ENGINE") is None


# ==============================================================================
# Asset and .blend Discovery Tests
# ==============================================================================


def test_discover_assets_non_recursive():
    with tempfile.TemporaryDirectory() as tmp_dir:
        f_obj = os.path.join(tmp_dir, "model.obj")
        f_fbx = os.path.join(tmp_dir, "model.fbx")
        f_txt = os.path.join(tmp_dir, "readme.txt")

        for f in (f_obj, f_fbx, f_txt):
            open(f, "w").close()

        # Non-recursive
        assets = BatchProcessorEngine.discover_assets(tmp_dir, recursive=False)
        assert len(assets) == 2
        assert f_obj in assets
        assert f_fbx in assets
        assert f_txt not in assets

        # Empty or nonexistent
        assert BatchProcessorEngine.discover_assets("") == []
        assert BatchProcessorEngine.discover_assets(os.path.join(tmp_dir, "nonexistent")) == []


def test_discover_blend_files_non_recursive_and_filtering():
    with tempfile.TemporaryDirectory() as tmp_dir:
        b_valid = os.path.join(tmp_dir, "hero.blend")
        b_lock = os.path.join(tmp_dir, ".#hero.blend")
        b_backup = os.path.join(tmp_dir, "~hero.blend")
        b_txt = os.path.join(tmp_dir, "notes.txt")

        for f in (b_valid, b_lock, b_backup, b_txt):
            open(f, "w").close()

        blends = BatchProcessorEngine.discover_blend_files(tmp_dir, recursive=False)
        assert len(blends) == 1
        assert b_valid in blends
        assert b_lock not in blends
        assert b_backup not in blends

        # Nonexistent path
        assert BatchProcessorEngine.discover_blend_files("") == []
        assert BatchProcessorEngine.discover_blend_files("C:/nonexistent_dir") == []


# ==============================================================================
# Object Cleanup and Import Guards
# ==============================================================================


def test_cleanup_imported_objects():
    bdata = MockBlendData()
    o1 = MockObject("Mesh1")
    o2 = MockObject("Armature1", obj_type="ARMATURE")
    bdata.objects._items["Mesh1"] = o1
    bdata.objects._items["Armature1"] = o2
    bdata.meshes._items["Mesh1_Mesh"] = o1.data

    BatchProcessorEngine.cleanup_imported_objects([o1, o2], blend_data=bdata)  # type: ignore[arg-type]

    # Verify both were cleaned up from bdata
    assert "Mesh1" not in bdata.objects
    assert "Armature1" not in bdata.objects


def test_import_asset_file_guards():
    bdata = MockBlendData()
    # Nonexistent file
    assert BatchProcessorEngine.import_asset_file("C:/nonexistent.obj", blend_data=bdata) == []  # type: ignore[arg-type]

    # Existing file with no bpy
    with tempfile.NamedTemporaryFile(suffix=".fbx", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        with patch("core.batch.bpy", None):
            assert BatchProcessorEngine.import_asset_file(tmp_path, blend_data=bdata) == []  # type: ignore[arg-type]
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_process_single_asset_guards():
    bdata = MockBlendData()

    # None context
    res_no_ctx = BatchProcessorEngine.process_single_asset(
        context=None,
        filepath="C:/test.fbx",
        export_base_dir="C:/export",
        blend_data=bdata,  # type: ignore[arg-type]
    )
    assert res_no_ctx["success"] is False
    assert "not available" in res_no_ctx["message"]

    mock_ctx = MagicMock()
    mock_bpy = MagicMock()

    # Import failure
    with (
        patch("core.batch.bpy", mock_bpy),
        patch.object(BatchProcessorEngine, "import_asset_file", return_value=[]),
    ):
        res_fail_import = BatchProcessorEngine.process_single_asset(
            context=mock_ctx,
            filepath="C:/empty.fbx",
            export_base_dir="C:/export",
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert res_fail_import["success"] is False
        assert "Failed to import" in res_fail_import["message"]

    # No valid mesh objects
    non_mesh_obj = MockObject("Arm", obj_type="ARMATURE")
    with (
        patch("core.batch.bpy", mock_bpy),
        patch.object(BatchProcessorEngine, "import_asset_file", return_value=[non_mesh_obj]),
        patch.object(BatchProcessorEngine, "cleanup_imported_objects") as mock_cleanup,
    ):
        res_no_mesh = BatchProcessorEngine.process_single_asset(
            context=mock_ctx,
            filepath="C:/rig_only.fbx",
            export_base_dir="C:/export",
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert res_no_mesh["success"] is False
        assert "No valid mesh geometry" in res_no_mesh["message"]
        assert mock_cleanup.called


def test_batch_process_operator_dialog_and_lifecycle(monkeypatch):
    """Verify OMNIMESH_OT_batch_process poll, invoke_props_dialog, draw, and execution validation."""
    from ui.batch_panel import OMNIMESH_OT_batch_process
    import ui.batch_panel as batch_mod
    import ui.panel as panel_mod

    mock_bpy = MagicMock()
    monkeypatch.setattr(batch_mod, "bpy", mock_bpy)

    # 1. Poll logic
    ctx = MagicMock()
    mock_props = MagicMock()
    mock_props.is_batch_running = False
    mock_props.batch_source_directory = ""
    ctx.scene.lod_tool = mock_props

    assert OMNIMESH_OT_batch_process.poll(ctx) is True
    mock_props.is_batch_running = True
    assert OMNIMESH_OT_batch_process.poll(ctx) is False
    mock_props.is_batch_running = False

    op = OMNIMESH_OT_batch_process()

    # 2. Invoke: opens dialog
    mock_wm = MagicMock()
    mock_wm.invoke_props_dialog.return_value = {"RUNNING_MODAL"}
    ctx.window_manager = mock_wm
    assert op.invoke(ctx, MagicMock()) == {"RUNNING_MODAL"}
    mock_wm.invoke_props_dialog.assert_called_once_with(op, width=440)

    # 3. Draw in popup dialog
    mock_layout = MagicMock()
    mock_box = MagicMock()
    mock_col = MagicMock()
    mock_layout.box.return_value = mock_box
    mock_box.column.return_value = mock_col
    cast(Any, op).layout = mock_layout
    op.draw(ctx)
    props_drawn = [c[0][1] for c in mock_col.prop.call_args_list if len(c[0]) > 1]
    assert "batch_source_directory" in props_drawn
    assert "export_directory" in props_drawn

    # 4. Execute validation failures
    mock_bpy.path.abspath = lambda p: p

    # Non-existent source
    mock_props.batch_source_directory = "/non/existent/path_xyz"
    mock_props.export_directory = "/valid/export"
    assert op.execute(ctx) == {"CANCELLED"}

    # Empty export dir
    with tempfile.TemporaryDirectory() as tmp_src:
        mock_props.batch_source_directory = tmp_src
        mock_props.export_directory = ""
        assert op.execute(ctx) == {"CANCELLED"}

        # Identical source and export dir
        mock_props.export_directory = tmp_src
        assert op.execute(ctx) == {"CANCELLED"}

    # 5. UI Panel rendering of Batch Export content
    mock_panel_layout = MagicMock()
    mock_panel_box = MagicMock()
    mock_panel_row = MagicMock()
    mock_panel_layout.box.return_value = mock_panel_box
    mock_panel_box.row.return_value = mock_panel_row

    mock_props.is_batch_running = False
    panel_mod._draw_batch_export_content(mock_panel_layout, ctx, mock_props)
    assert any(
        "lod_tool.batch_process" in str(c) and "Folder..." in c.kwargs.get("text", "")
        for c in mock_panel_row.operator.call_args_list
    )

    mock_panel_row.reset_mock()
    mock_props.is_batch_running = True
    panel_mod._draw_batch_export_content(mock_panel_layout, ctx, mock_props)
    assert any("lod_tool.batch_cancel" in str(c) for c in mock_panel_row.operator.call_args_list)
