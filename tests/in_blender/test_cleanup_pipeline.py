"""
In-Blender Integration Tests for LOD0 Mesh/Material Sanitization.
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
    """Verify LOD0 topology sanitization and material cleanup operators."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_clean_and_repair_mesh_heals_topology(self) -> None:
        """Verify clean_and_repair_mesh purges loose verts, degenerates, and splits bowties."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            obj = create_dirty_mesh("SM_DirtyRepair")
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)

            import bmesh

            mesh_data: Any = obj.data
            initial_verts = len(mesh_data.vertices)
            initial_polys = len(mesh_data.polygons)

            props: Any = getattr(scene, "lod_tool", None)
            if props is None:
                return
            props.cleanup_enable_split_non_manifold = True
            props.cleanup_enable_weld = False
            props.cleanup_normal_policy = "OFF"

            ops: Any = cast(Any, bpy.ops).lod_tool
            res = ops.clean_and_repair_mesh()
            self.assertEqual(res, {"FINISHED"})

            bm = bmesh.new()
            try:
                bm.from_mesh(mesh_data)
                loose_verts = sum(1 for v in bm.verts if len(v.link_edges) == 0)
                degen_tris = sum(1 for f in bm.faces if f.calc_area() <= 1e-10)
                self.assertEqual(loose_verts, 0, "Loose vertices must be 0 after repair.")
                self.assertEqual(degen_tris, 0, "Degenerates must be 0 after repair.")
                self.assertLess(len(bm.verts), initial_verts)
                self.assertLess(len(bm.faces), initial_polys)
            finally:
                bm.free()

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
            self.assertEqual(len(cube_data.materials), 0)
            self.assertTrue(all(slot.material is None for slot in cube_obj.material_slots))

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

    def test_clean_and_repair_materials_wires_all_cleanup_options(self) -> None:
        """Verify clean_and_repair_materials executes micro-consolidation, deduplication, texture repair, and orphan purge."""
        import bmesh

        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            mesh = bpy.data.meshes.new("SM_FullMatClean_Mesh")
            obj = bpy.data.objects.new("SM_FullMatClean", mesh)
            scene.collection.objects.link(obj)

            bm = bmesh.new()
            # Large quad (area = 4.0) -> dominant material M_Dom
            lv = [bm.verts.new(c) for c in ((0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0))]
            f_dom = bm.faces.new(lv)
            f_dom.material_index = 0
            # Micro quad (area = 0.01 -> ~0.25% < 1.0%) -> micro material M_Micro
            mv = [bm.verts.new(c) for c in ((10, 0, 0), (10.1, 0, 0), (10.1, 0.1, 0), (10, 0.1, 0))]
            f_micro = bm.faces.new(mv)
            f_micro.material_index = 1
            bm.to_mesh(mesh)
            bm.free()

            mat_dom = bpy.data.materials.new("M_Dom")
            mat_dom.use_nodes = True
            assert mat_dom.node_tree is not None
            bsdf = next(n for n in mat_dom.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            img_broken = bpy.data.images.new("MissingImg", width=8, height=8)
            img_broken.source = "FILE"
            img_broken.filepath = "/nonexistent/path/missing_tex.png"
            tex_node = mat_dom.node_tree.nodes.new("ShaderNodeTexImage")
            cast(Any, tex_node).image = img_broken
            mat_dom.node_tree.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])

            mat_micro = bpy.data.materials.new("M_Micro")
            mat_orphan = bpy.data.materials.new("M_ZeroUserOrphan")

            mesh.materials.append(mat_dom)  # slot 0
            mesh.materials.append(mat_micro)  # slot 1
            mesh.materials.append(mat_dom)  # slot 2 duplicate

            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)

            props: Any = getattr(scene, "lod_tool", None)
            if props is None:
                return
            ops: Any = cast(Any, bpy.ops).lod_tool

            # Negative boundary: all 8 cleanup flags False -> nothing modified
            props.mat_cleanup_purge_unused_slots = False
            props.mat_cleanup_deduplicate_slots = False
            props.mat_cleanup_merge_duplicate_datablocks = False
            props.mat_cleanup_remove_orphan_nodes = False
            props.mat_cleanup_enable_micro_consolidation = False
            props.mat_cleanup_repair_missing_textures = False
            props.mat_cleanup_purge_orphans_blendfile = False
            self.assertEqual(ops.clean_and_repair_materials(), {"FINISHED"})
            self.assertEqual(len(mesh.materials), 3)
            self.assertIn("M_ZeroUserOrphan", bpy.data.materials)

            # Positive: enable remaining 5 flags + purge
            props.mat_cleanup_purge_unused_slots = True
            props.mat_cleanup_deduplicate_slots = True
            props.mat_cleanup_enable_micro_consolidation = True
            props.mat_cleanup_micro_area_pct = 1.0
            props.mat_cleanup_repair_missing_textures = True
            props.mat_cleanup_purge_orphans_blendfile = True
            self.assertEqual(ops.clean_and_repair_materials(), {"FINISHED"})

            self.assertEqual(len(mesh.materials), 1)
            self.assertEqual(mesh.materials[0], mat_dom)
            self.assertFalse(any(n.type == "TEX_IMAGE" for n in mat_dom.node_tree.nodes))
            self.assertNotIn("M_ZeroUserOrphan", bpy.data.materials)
            _ = mat_orphan


if __name__ == "__main__":
    unittest.main()
