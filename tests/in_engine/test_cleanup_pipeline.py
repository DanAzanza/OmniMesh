"""
In-Engine Integration Tests for LOD0 Preflight Inspection and Mesh/Material Sanitization.
"""

from __future__ import annotations

import unittest

try:
    import bpy
    from tests.in_engine.fixtures import create_dirty_mesh, in_engine_sandbox
except ImportError:
    bpy = None
    create_dirty_mesh = None  # type: ignore
    in_engine_sandbox = None  # type: ignore


class TestCleanupPipeline(unittest.TestCase):
    """Verify LOD0 preflight analysis and topology sanitization operators."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_preflight_detects_all_synthetic_defects(self) -> None:
        """Verify inspect_lod0 accurately detects unapplied scale, loose verts, and degenerates."""
        with in_engine_sandbox() as scene:
            obj = create_dirty_mesh("SM_DirtyPreflight")
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)

            res = bpy.ops.lod_tool.inspect_lod0()
            self.assertEqual(res, {"FINISHED"})

            props = scene.lod_tool
            self.assertTrue(props.preflight_unapplied_scale, "Should detect unapplied scale (0.01).")
            self.assertEqual(props.preflight_loose_verts, 2, "Should detect exactly 2 loose floating vertices.")
            self.assertEqual(props.preflight_degenerate_tris, 1, "Should detect 1 zero-area degenerate triangle.")
            self.assertFalse(props.preflight_is_clean, "Mesh must be marked as not clean.")
            self.assertIn("Issues:", props.preflight_summary_text)

    def test_clean_and_repair_mesh_heals_topology(self) -> None:
        """Verify clean_and_repair_mesh purges loose verts, degenerates, and splits bowties."""
        with in_engine_sandbox() as scene:
            obj = create_dirty_mesh("SM_DirtyRepair")
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)

            props = scene.lod_tool
            props.cleanup_enable_split_non_manifold = True
            props.cleanup_enable_weld = False
            props.cleanup_normal_policy = "OFF"

            res = bpy.ops.lod_tool.clean_and_repair_mesh()
            self.assertEqual(res, {"FINISHED"})
            self.assertIn("Cleaned:", props.last_cleanup_summary)
            self.assertIn("loose verts", props.last_cleanup_summary)
            self.assertIn("degenerate faces", props.last_cleanup_summary)
            self.assertIn("bowties split", props.last_cleanup_summary)

            # Re-inspect to verify topology defects are fully resolved
            bpy.ops.lod_tool.inspect_lod0()
            self.assertEqual(props.preflight_loose_verts, 0, "Loose vertices must be 0 after repair.")
            self.assertEqual(props.preflight_degenerate_tris, 0, "Degenerates must be 0 after repair.")

    def test_clean_and_repair_materials_purges_unused_slots(self) -> None:
        """Verify clean_and_repair_materials purges empty or unused material slots."""
        with in_engine_sandbox() as scene:
            mesh = bpy.data.meshes.new("SM_MatTest_Mesh")
            cube_obj = bpy.data.objects.new("SM_MatTest", mesh)
            scene.collection.objects.link(cube_obj)

            # Add an empty slot and an unassigned slot
            mat = bpy.data.materials.new("M_Assigned")
            cube_obj.data.materials.append(mat)
            cube_obj.data.materials.append(None)  # Empty slot

            bpy.context.view_layer.objects.active = cube_obj
            cube_obj.select_set(True)

            props = scene.lod_tool
            props.mat_cleanup_purge_unused_slots = True
            res = bpy.ops.lod_tool.clean_and_repair_materials()
            self.assertEqual(res, {"FINISHED"})
            self.assertIn("Purged", props.last_material_cleanup_summary)


if __name__ == "__main__":
    unittest.main()
