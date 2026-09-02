"""
In-Engine Integration Tests for Multi-Engine Export Packages (UE5, Unity 6, Godot 4, MSFS 2024).
"""

from __future__ import annotations

import logging
import os
import tempfile
import unittest

logger = logging.getLogger(__name__)

try:
    import addon_utils
    import bpy
    from tests.in_engine.fixtures import create_hierarchy_fixture, in_engine_sandbox
except ImportError:
    bpy = None
    addon_utils = None
    create_hierarchy_fixture = None  # type: ignore
    in_engine_sandbox = None  # type: ignore


class TestExportPipeline(unittest.TestCase):
    """Verify 1-click multi-engine export package generation and XML/FBX/glTF integrity."""

    @classmethod
    def setUpClass(cls) -> None:
        if not bpy or not addon_utils:
            return
        # Ensure native exporter addons are enabled
        for addon in ("io_scene_fbx", "io_scene_gltf2"):
            try:
                addon_utils.enable(addon, default_set=False)
            except Exception as exc:
                logger.debug("Native exporter addon enable skipped for %s: %s", addon, exc)

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_multi_engine_exports_generate_valid_files(self) -> None:
        """Verify exports create valid disk artifacts for MSFS 2024, UE5, Unity 6, and Godot 4."""
        with in_engine_sandbox() as scene:
            mesh_objs = create_hierarchy_fixture("SM_ExpAsset")
            for obj in mesh_objs:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = mesh_objs[0]

            props = scene.lod_tool
            props.export_base_name = "SM_ExpAsset"
            props.export_packed_textures = False
            props.enable_live_sync = False

            bpy.ops.lod_tool.analyze_and_configure()
            bpy.ops.lod_tool.generate_all()

            with tempfile.TemporaryDirectory() as tmpdir:
                props.export_directory = tmpdir

                # 1. Test MSFS 2024 (glTF + XML)
                props.target_engine = "MSFS_2024"
                res_msfs = bpy.ops.lod_tool.export_engine_package()
                self.assertEqual(res_msfs, {"FINISHED"})
                xml_path = os.path.join(tmpdir, "SM_ExpAsset.xml")
                self.assertTrue(os.path.exists(xml_path), "MSFS XML file must exist.")
                with open(xml_path, "r", encoding="utf-8") as f:
                    xml_content = f.read()
                    self.assertIn("<LODS>", xml_content)
                    self.assertIn("minSize=", xml_content)

                # 2. Test Unreal Engine 5 (Single Multi-LOD FBX)
                props.target_engine = "UE5"
                res_ue5 = bpy.ops.lod_tool.export_engine_package()
                self.assertEqual(res_ue5, {"FINISHED"})
                ue5_fbx = os.path.join(tmpdir, "SM_ExpAsset.fbx")
                self.assertTrue(os.path.exists(ue5_fbx), "UE5 FBX file must exist.")
                self.assertGreater(os.path.getsize(ue5_fbx), 0)

                # 3. Test Unity 6 (Multi-LOD FBX)
                props.target_engine = "UNITY_6"
                res_unity = bpy.ops.lod_tool.export_engine_package()
                self.assertEqual(res_unity, {"FINISHED"})
                unity_fbx = os.path.join(tmpdir, "SM_ExpAsset.fbx")
                self.assertTrue(os.path.exists(unity_fbx), "Unity FBX file must exist.")
                self.assertGreater(os.path.getsize(unity_fbx), 0)

                # 4. Test Godot 4 (glTF with -lod suffixes)
                props.target_engine = "GODOT_4"
                res_godot = bpy.ops.lod_tool.export_engine_package()
                self.assertEqual(res_godot, {"FINISHED"})
                godot_files = [
                    f for f in os.listdir(tmpdir) if f.startswith("SM_ExpAsset") and f.endswith((".gltf", ".glb"))
                ]
                self.assertGreater(len(godot_files), 0, "Godot glTF/GLB file must exist.")


if __name__ == "__main__":
    unittest.main()
