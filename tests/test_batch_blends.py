"""
Unit tests for OmniMesh Batch .blend File Discovery and Mirrored Hierarchy.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
import unittest

from core.batch import BatchProcessorEngine


class TestBatchBlends(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="omnimesh_batch_test_")
        self.source_dir = Path(self.temp_dir) / "Source"
        self.export_dir = Path(self.temp_dir) / "Export"
        self.source_dir.mkdir(parents=True)
        self.export_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_discover_blend_files_recursive(self) -> None:
        # Create nested blend files
        prop_dir = self.source_dir / "Props" / "Chairs"
        prop_dir.mkdir(parents=True)
        (prop_dir / "chair1.blend").write_text("", encoding="utf-8")
        (prop_dir / "chair2.blend").write_text("", encoding="utf-8")

        veh_dir = self.source_dir / "Vehicles"
        veh_dir.mkdir(parents=True)
        (veh_dir / "car.blend").write_text("", encoding="utf-8")

        # Create lock/backup files that MUST be ignored
        (prop_dir / "chair1.blend1").write_text("", encoding="utf-8")
        (prop_dir / "chair1.blend2").write_text("", encoding="utf-8")
        (prop_dir / ".~chair1.blend").write_text("", encoding="utf-8")
        (veh_dir / ".car.blend").write_text("", encoding="utf-8")
        (veh_dir / "car.blend@").write_text("", encoding="utf-8")
        (veh_dir / "car.fbx").write_text("", encoding="utf-8")

        files = BatchProcessorEngine.discover_blend_files(str(self.source_dir), recursive=True)
        self.assertEqual(len(files), 3)
        basenames = sorted(os.path.basename(f) for f in files)
        self.assertEqual(basenames, ["car.blend", "chair1.blend", "chair2.blend"])

    def test_discover_ignores_export_folder_if_nested(self) -> None:
        nested_export = self.source_dir / "Exported_Packages"
        nested_export.mkdir(parents=True)
        (nested_export / "exported_asset.blend").write_text("", encoding="utf-8")

        real_asset = self.source_dir / "model.blend"
        real_asset.write_text("", encoding="utf-8")

        files = BatchProcessorEngine.discover_blend_files(
            str(self.source_dir), recursive=True, export_dir=str(nested_export)
        )
        self.assertEqual(len(files), 1)
        self.assertEqual(os.path.basename(files[0]), "model.blend")

    def test_compute_mirrored_export_path(self) -> None:
        blend_file = self.source_dir / "Characters" / "Hero (Armor)" / "warrior.blend"
        blend_file.parent.mkdir(parents=True)
        blend_file.write_text("", encoding="utf-8")

        target_dir, asset_name = BatchProcessorEngine.compute_mirrored_export_path(
            str(blend_file), str(self.source_dir), str(self.export_dir)
        )

        expected_sub = os.path.join("Characters", "Hero__Armor_")
        self.assertTrue(target_dir.endswith(expected_sub) or target_dir.endswith(expected_sub.replace("/", "\\")))
        self.assertEqual(asset_name, "warrior")

    def test_compute_mirrored_export_path_root_file(self) -> None:
        blend_file = self.source_dir / "single_prop.blend"
        blend_file.write_text("", encoding="utf-8")

        target_dir, asset_name = BatchProcessorEngine.compute_mirrored_export_path(
            str(blend_file), str(self.source_dir), str(self.export_dir)
        )

        self.assertEqual(os.path.normpath(target_dir), os.path.normpath(str(self.export_dir)))
        self.assertEqual(asset_name, "single_prop")


if __name__ == "__main__":
    unittest.main()
