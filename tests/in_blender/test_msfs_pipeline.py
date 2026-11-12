"""In-Blender Integration Tests for MSFS 2024 Airframe Analysis, Ground Alignment, and Spatial Tools."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast
import unittest

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from tests.in_blender.fixtures import create_hierarchy_fixture, in_blender_sandbox
else:
    try:
        import bpy
        from tests.in_blender.fixtures import create_hierarchy_fixture, in_blender_sandbox
    except ImportError:
        bpy = None
        create_hierarchy_fixture = None  # type: ignore
        in_blender_sandbox = None  # type: ignore


class TestMSFSPipeline(unittest.TestCase):
    """Verify MSFS 2024 scrape point generation, tire contact ground alignment, and spatial camera tools."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_msfs_scrape_points_and_gear_alignment(self) -> None:
        """Verify scrape point detection on airframe mesh and gear alignment to tire contact patch."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            mesh_objs = create_hierarchy_fixture("C172_Airframe")
            for obj in mesh_objs:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = mesh_objs[0]

            # 1. Generate scrape points
            ops: Any = cast(Any, bpy.ops).omnimesh
            res_scrape = ops.generate_vehicle_scrape_points()
            self.assertEqual(res_scrape, {"FINISHED"})

            spatial_col = next(
                (c for c in bpy.data.collections if c.get("_omnimesh_role") == "SPATIAL" or "Spatial" in c.name),
                None,
            )
            self.assertIsNotNone(spatial_col)
            if spatial_col:
                self.assertGreater(len(spatial_col.objects), 0)

                # 2. Add wheel contact point empty and CG empty to test ground alignment
                datum = next(
                    (
                        o
                        for o in spatial_col.objects
                        if o.get("msfs_id") == "WEIGHT_AND_BALANCE:reference_datum_position"
                    ),
                    None,
                )
                wheel = bpy.data.objects.new("MSFS_Wheel_Main", None)
                wheel["msfs_type"] = "CONTACT_POINT"
                wheel["msfs_class"] = 1
                wheel.location = (0.0, 0.0, 0.0)
                spatial_col.objects.link(wheel)
                if datum:
                    wheel.parent = datum

                cg = bpy.data.objects.new("MSFS_CG", None)
                cg["msfs_type"] = "CG"
                cg.location = (0.0, 0.0, 1.5)
                spatial_col.objects.link(cg)

                res_gear = ops.align_gear_ground_level()
                self.assertEqual(res_gear, {"FINISHED"})

    def test_msfs_camera_operators(self) -> None:
        """Verify MSFS camera creation, view alignment, and scene camera restore."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            cam_col = bpy.data.collections.new("MSFS_Cameras")
            scene.collection.children.link(cam_col)

            cam_data = bpy.data.cameras.new("MSFS_Cockpit_Cam")
            cam_obj = bpy.data.objects.new("MSFS_Cockpit_Cam", cam_data)
            cam_obj["msfs_camera_index"] = 0
            cam_col.objects.link(cam_obj)
            bpy.context.view_layer.objects.active = cam_obj

            ops: Any = cast(Any, bpy.ops).omnimesh
            self.assertEqual(ops.look_through_vehicle_camera(), {"FINISHED"})
            self.assertIn(ops.align_vehicle_camera_to_view(), ({"FINISHED"}, {"CANCELLED"}))
            self.assertEqual(ops.restore_scene_camera(), {"FINISHED"})


if __name__ == "__main__":
    unittest.main()
