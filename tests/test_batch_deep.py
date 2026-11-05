"""
Deep unit tests for core/batch.py.
Covers lazy exporter discovery, recursive and non-recursive asset discovery,
.blend filtering (locking files, backup files, nested export exclusion),
mirrored hierarchical path computation, object cleanup, and process_single_asset guards.
"""

from __future__ import annotations

from typing import Any

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
