"""
In-Blender Integration Tests for LOD0 Preflight Inspection and Mesh/Material Sanitization.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import unittest

if TYPE_CHECKING:
    import bpy
    from tests.in_blender.fixtures import create_dirty_mesh, in_blender_sandbox
else:
    try:
        import bpy
        from tests.in_blender.fixtures import create_dirty_mesh, in_blender_sandbox
    except ImportError:
        bpy = None
        create_dirty_mesh = None  # type: ignore
        in_blender_sandbox = None  # type: ignore


class TestCleanupPipeline(unittest.TestCase):
    """Verify LOD0 preflight analysis and topology sanitization operators."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_preflight_detects_all_synthetic_defects(self) -> None:
        """Verify inspect_lod0 accurately detects unapplied scale, loose verts, and degenerates."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            obj = create_dirty_mesh("SM_DirtyPreflight")
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)

            ops: Any = cast(Any, bpy.ops).lod_tool
            res = ops.inspect_lod0()
            self.assertEqual(res, {"FINISHED"})

            props: Any = getattr(scene, "lod_tool", None)
            if props is None:
                return
            self.assertTrue(props.preflight_unapplied_scale, "Should detect unapplied scale (0.01).")
            self.assertEqual(props.preflight_loose_verts, 2, "Should detect exactly 2 loose floating vertices.")
            self.assertEqual(props.preflight_degenerate_tris, 1, "Should detect 1 zero-area degenerate triangle.")
            self.assertFalse(props.preflight_is_clean, "Mesh must be marked as not clean.")
            self.assertIn("Issues:", props.preflight_summary_text)

    def test_clean_and_repair_mesh_heals_topology(self) -> None:
        """Verify clean_and_repair_mesh purges loose verts, degenerates, and splits bowties."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            obj = create_dirty_mesh("SM_DirtyRepair")
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)

            props: Any = getattr(scene, "lod_tool", None)
            if props is None:
                return
            props.cleanup_enable_split_non_manifold = True
            props.cleanup_enable_weld = False
            props.cleanup_normal_policy = "OFF"

            ops: Any = cast(Any, bpy.ops).lod_tool
            res = ops.clean_and_repair_mesh()
            self.assertEqual(res, {"FINISHED"})
            self.assertIn("Cleaned:", props.last_cleanup_summary)
            self.assertIn("loose verts", props.last_cleanup_summary)
            self.assertIn("degenerate faces", props.last_cleanup_summary)
            self.assertIn("bowties split", props.last_cleanup_summary)

            # Re-inspect to verify topology defects are fully resolved
            ops.inspect_lod0()
            self.assertEqual(props.preflight_loose_verts, 0, "Loose vertices must be 0 after repair.")
            self.assertEqual(props.preflight_degenerate_tris, 0, "Degenerates must be 0 after repair.")

    def test_clean_and_repair_materials_purges_unused_slots(self) -> None:
        """Verify clean_and_repair_materials purges empty or unused material slots."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            mesh = bpy.data.meshes.new("SM_MatTest_Mesh")
            cube_obj = bpy.data.objects.new("SM_MatTest", mesh)
            scene.collection.objects.link(cube_obj)

            # Add an empty slot and an unassigned slot
            mat = bpy.data.materials.new("M_Assigned")
            cube_data: Any = cube_obj.data
            cube_data.materials.append(mat)
            cube_data.materials.append(None)  # Empty slot

            bpy.context.view_layer.objects.active = cube_obj
            cube_obj.select_set(True)

            props: Any = getattr(scene, "lod_tool", None)
            if props is None:
                return
            props.mat_cleanup_purge_unused_slots = True
            ops: Any = cast(Any, bpy.ops).lod_tool
            res = ops.clean_and_repair_materials()
            self.assertEqual(res, {"FINISHED"})
            self.assertIn("Purged", props.last_material_cleanup_summary)

    def test_sanitize_mesh_full_direct_bmesh(self) -> None:
        """Verify MeshSanitizer.sanitize_mesh_full coordinates all 3 tiers directly on live BMesh."""
        import bmesh
        from core.sanitizer import MeshSanitizer, SanitizeOptions

        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            obj = create_dirty_mesh("SM_SanitizeDirect")
            mesh = cast("bpy.types.Mesh", obj.data)
            bm = bmesh.new()
            bm.from_mesh(mesh)

            options = SanitizeOptions(
                enable_weld=True,
                epsilon_merge=0.001,
                enable_split_non_manifold=True,
                enable_fill_holes=True,
                hole_max_edges=8,
                enable_triangulate_ngons=True,
                enable_cull_micro_islands=True,
                w_crit=0.01,
            )
            stats = MeshSanitizer.sanitize_mesh_full(bm, options=options)
            bm.to_mesh(mesh)
            bm.free()

            self.assertGreaterEqual(stats.get("loose_verts", 0), 2)
            self.assertGreaterEqual(stats.get("zero_faces", 0), 1)
            self.assertGreaterEqual(stats.get("split_bowties", 0), 1)

    def test_topology_repair_cull_subpixel_islands(self) -> None:
        """Verify cull_subpixel_islands removes micro-debris while preserving primary geometry."""
        import bmesh
        from core.topology_repair import TopologyRepairEngine

        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            _mesh = bpy.data.meshes.new("SM_IslandTest_Mesh")
            bm = bmesh.new()
            # 1. Main Cube (surface area = 24.0)
            bmesh.ops.create_cube(bm, size=2.0)
            # 2. Micro triangle (area ~ 0.00005, subpixel debris)
            v1 = bm.verts.new((10.0, 0.0, 0.0))
            v2 = bm.verts.new((10.01, 0.0, 0.0))
            v3 = bm.verts.new((10.0, 0.01, 0.0))
            bm.faces.new((v1, v2, v3))
            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            # Before cull: 6 cube faces + 1 micro face = 7 faces
            self.assertEqual(len(bm.faces), 7)
            removed = TopologyRepairEngine.cull_subpixel_islands(bm, w_crit=0.05)
            self.assertEqual(removed, 1, "Exactly 1 subpixel island face should be culled.")
            self.assertEqual(len(bm.faces), 6, "Only the 6 primary cube faces must remain.")
            bm.free()

    def test_topology_repair_fill_small_boundary_holes(self) -> None:
        """Verify fill_small_boundary_holes identifies and caps open polygon rings."""
        import bmesh
        from core.topology_repair import TopologyRepairEngine

        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            _mesh = bpy.data.meshes.new("SM_HoleTest_Mesh")
            bm = bmesh.new()
            # Create cube and delete one face to create an open 4-edge hole
            bmesh.ops.create_cube(bm, size=2.0)
            bm.faces.ensure_lookup_table()
            face_to_remove = bm.faces[0]
            bmesh.ops.delete(bm, geom=[face_to_remove], context="FACES_ONLY")
            self.assertEqual(len(bm.faces), 5)

            filled = TopologyRepairEngine.fill_small_boundary_holes(bm, max_edges=6)
            self.assertEqual(filled, 1, "The 4-edge hole must be detected and filled.")
            # 5 original quads + 2 beauty-triangulated faces capping the 4-edge hole = 7 faces
            self.assertEqual(len(bm.faces), 7, "Mesh should have 5 quads + 2 triangulated hole faces.")
            self.assertFalse(any(e.is_boundary for e in bm.edges), "Mesh must be fully watertight.")
            bm.free()


if __name__ == "__main__":
    unittest.main()
