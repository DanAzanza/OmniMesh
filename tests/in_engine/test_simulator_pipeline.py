"""
In-Engine Integration Tests for Viewport Camera Parameter Extraction and Real-time LOD Simulation.
"""

from __future__ import annotations

import unittest

try:
    import bpy
    from core.simulator import LODSimulatorEngine, extract_viewport_camera_params
    from tests.in_engine.fixtures import create_hierarchy_fixture, in_engine_sandbox
except ImportError:
    bpy = None
    LODSimulatorEngine = None  # type: ignore
    extract_viewport_camera_params = None  # type: ignore
    create_hierarchy_fixture = None  # type: ignore
    in_engine_sandbox = None  # type: ignore


class TestSimulatorPipeline(unittest.TestCase):
    """Verify scene indexing, camera distance tracking, and simulation HUD data structures."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")
        LODSimulatorEngine._tracked_assets.clear()

    def tearDown(self) -> None:
        LODSimulatorEngine._tracked_assets.clear()

    def test_simulator_index_scene_assets(self) -> None:
        """Verify LODSimulatorEngine indexes sibling collections accurately."""
        with in_engine_sandbox() as scene:
            mesh_objs = create_hierarchy_fixture("SM_SimAsset")
            for obj in mesh_objs:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = mesh_objs[0]

            props = scene.lod_tool
            props.export_base_name = "SM_SimAsset"

            bpy.ops.lod_tool.analyze_and_configure()
            bpy.ops.lod_tool.generate_all()

            # Index scene assets
            tracked_count = LODSimulatorEngine.index_scene_assets(scene)
            self.assertEqual(tracked_count, 1, "Must index exactly 1 asset hierarchy.")

            tracked = LODSimulatorEngine.get_tracked_assets()
            self.assertIn("SM_SimAsset", tracked)
            record = tracked["SM_SimAsset"]
            self.assertEqual(len(record.tier_objects), len(props.lods))

    def test_extract_viewport_camera_params(self) -> None:
        """Verify extract_viewport_camera_params returns safe camera parameters in all view modes."""
        with in_engine_sandbox() as scene:
            # Create a scene camera
            cam_data = bpy.data.cameras.new("TestCamera")
            cam_obj = bpy.data.objects.new("TestCamera", cam_data)
            scene.collection.objects.link(cam_obj)
            cam_obj.location = (0.0, -10.0, 2.0)
            scene.camera = cam_obj

            cam_pos, fov_v_rad, is_perspective = extract_viewport_camera_params(None, None, None, scene)
            self.assertIsNotNone(cam_pos)
            self.assertGreater(fov_v_rad, 0.0)
            self.assertTrue(is_perspective)


if __name__ == "__main__":
    unittest.main()
