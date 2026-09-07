"""
Unit tests for OmniMesh Upward Project Detector and Live Link toggle operator.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
import unittest

from core.project_detector import detect_engine_project


class TestProjectDetector(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="omnimesh_detect_test_")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_detect_ue5_project_nested(self) -> None:
        project_root = Path(self.temp_dir) / "MyUE5Game"
        export_dir = project_root / "Content" / "Art" / "Props" / "Export"
        export_dir.mkdir(parents=True)
        (project_root / "MyUE5Game.uproject").write_text("{}", encoding="utf-8")

        detected = detect_engine_project(str(export_dir), "UE5")
        self.assertIsNotNone(detected)
        self.assertEqual(os.path.normpath(str(detected)), os.path.normpath(str(project_root)))

    def test_detect_ue5_filters_backup_projects(self) -> None:
        project_root = Path(self.temp_dir) / "MyUE5Game"
        export_dir = project_root / "Content" / "Export"
        export_dir.mkdir(parents=True)
        # Write only backup uproject
        (project_root / "MyUE5Game_backup.uproject").write_text("{}", encoding="utf-8")

        detected = detect_engine_project(str(export_dir), "UE5")
        self.assertIsNone(detected)

        # Now add real uproject
        (project_root / "MyUE5Game.uproject").write_text("{}", encoding="utf-8")
        detected = detect_engine_project(str(export_dir), "UE5")
        self.assertEqual(os.path.normpath(str(detected)), os.path.normpath(str(project_root)))

    def test_detect_unity6_project(self) -> None:
        project_root = Path(self.temp_dir) / "UnityProject"
        export_dir = project_root / "Assets" / "Models" / "Export"
        export_dir.mkdir(parents=True)
        proj_settings = project_root / "ProjectSettings"
        proj_settings.mkdir(parents=True)
        (proj_settings / "ProjectVersion.txt").write_text("m_EditorVersion: 6000.0.0f1", encoding="utf-8")

        detected = detect_engine_project(str(export_dir), "UNITY_6")
        self.assertIsNotNone(detected)
        self.assertEqual(os.path.normpath(str(detected)), os.path.normpath(str(project_root)))

    def test_detect_godot4_project(self) -> None:
        project_root = Path(self.temp_dir) / "GodotProject"
        export_dir = project_root / "scenes" / "models"
        export_dir.mkdir(parents=True)
        (project_root / "project.godot").write_text("config_version=5", encoding="utf-8")

        detected = detect_engine_project(str(export_dir), "GODOT_4")
        self.assertIsNotNone(detected)
        self.assertEqual(os.path.normpath(str(detected)), os.path.normpath(str(project_root)))

    def test_detect_msfs_project(self) -> None:
        project_root = Path(self.temp_dir) / "MyAirport"
        export_dir = project_root / "PackageSources" / "modelLib"
        export_dir.mkdir(parents=True)
        (project_root / "PackageDefinitions").mkdir(parents=True)

        detected = detect_engine_project(str(export_dir), "MSFS_2024")
        self.assertIsNotNone(detected)
        self.assertEqual(os.path.normpath(str(detected)), os.path.normpath(str(project_root)))

    def test_detect_returns_none_when_outside(self) -> None:
        scratch_dir = Path(self.temp_dir) / "ScratchExports"
        scratch_dir.mkdir()
        detected = detect_engine_project(str(scratch_dir), "UE5")
        self.assertIsNone(detected)

    def test_detect_empty_or_none(self) -> None:
        self.assertIsNone(detect_engine_project("", "UE5"))
        self.assertIsNone(detect_engine_project("non_existent_path_xyz", "UE5"))

    def test_detect_max_depth_respected(self) -> None:
        project_root = Path(self.temp_dir) / "DeepUE5"
        project_root.mkdir(parents=True)
        (project_root / "Deep.uproject").write_text("{}", encoding="utf-8")

        # Create path 10 levels deep
        deep_path = project_root
        for i in range(10):
            deep_path = deep_path / f"level_{i}"
        deep_path.mkdir(parents=True)

        # With max_depth=4, it should NOT reach project_root
        detected = detect_engine_project(str(deep_path), "UE5", max_depth=4)
        self.assertIsNone(detected)

        # With max_depth=12, it SHOULD reach project_root
        detected = detect_engine_project(str(deep_path), "UE5", max_depth=12)
        self.assertIsNotNone(detected)


if __name__ == "__main__":
    unittest.main()
