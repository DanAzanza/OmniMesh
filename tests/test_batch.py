"""
Unit tests for OmniMesh Batch Library Ingest Engine.
"""

from __future__ import annotations

import os
import tempfile
from core.batch import BatchProcessorEngine


def test_batch_processor_discover_assets_empty():
    assert BatchProcessorEngine.discover_assets("") == []
    assert BatchProcessorEngine.discover_assets("non_existent_folder_xyz_123") == []


def test_batch_processor_discover_assets_filtering():
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create dummy supported and unsupported files
        sub_dir = os.path.join(tmp_dir, "Props")
        os.makedirs(sub_dir, exist_ok=True)

        f1 = os.path.join(tmp_dir, "ModelA.fbx")
        f2 = os.path.join(tmp_dir, "ModelB.obj")
        f3 = os.path.join(sub_dir, "ModelC.gltf")
        f4 = os.path.join(sub_dir, "ModelD.glb")
        f_ignore = os.path.join(sub_dir, "Texture.png")
        f_ignore_txt = os.path.join(tmp_dir, "readme.txt")

        for p in (f1, f2, f3, f4, f_ignore, f_ignore_txt):
            with open(p, "w", encoding="utf-8") as f:
                f.write("test")

        # Recursive scan
        discovered_rec = BatchProcessorEngine.discover_assets(tmp_dir, recursive=True)
        assert len(discovered_rec) == 4
        assert os.path.abspath(f1) in discovered_rec
        assert os.path.abspath(f2) in discovered_rec
        assert os.path.abspath(f3) in discovered_rec
        assert os.path.abspath(f4) in discovered_rec

        # Non-recursive scan
        discovered_flat = BatchProcessorEngine.discover_assets(tmp_dir, recursive=False)
        assert len(discovered_flat) == 2
        assert os.path.abspath(f1) in discovered_flat
        assert os.path.abspath(f2) in discovered_flat


def test_batch_processor_single_asset_no_bpy():
    res = BatchProcessorEngine.process_single_asset(
        context=None,
        filepath="dummy_path.fbx",
        export_base_dir="dummy_export",
    )
    assert res["success"] is False
    assert "Blender" in res["message"] or "not available" in res["message"]


def test_batch_processor_import_asset_file_guards():
    assert BatchProcessorEngine.import_asset_file("") == []
    assert BatchProcessorEngine.import_asset_file("non_existent_path.fbx") == []


def test_batch_processor_cleanup_imported_objects():
    # Should not throw on empty/None
    BatchProcessorEngine.cleanup_imported_objects([])
    BatchProcessorEngine.cleanup_imported_objects([None, object()])
