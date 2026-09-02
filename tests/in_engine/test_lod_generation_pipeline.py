"""
In-Engine Integration Tests for Logarithmic Tier Generation, Sibling Collection DAGs, and Rigged Clamping.
"""

from __future__ import annotations

import unittest

try:
    import bpy
    from tests.in_engine.fixtures import create_hierarchy_fixture, create_skinned_mesh, in_engine_sandbox
except ImportError:
    bpy = None
    create_hierarchy_fixture = None  # type: ignore
    create_skinned_mesh = None  # type: ignore
    in_engine_sandbox = None  # type: ignore


class TestLODGenerationPipeline(unittest.TestCase):
    """Verify end-to-end LOD tier calculation, sibling collection generation, and hierarchy cloning."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_analyze_and_configure_logarithmic_tiers(self) -> None:
        """Verify analyze_and_configure sets up logarithmic screen tiers and bounding radius."""
        with in_engine_sandbox() as scene:
            mesh_objs = create_hierarchy_fixture("SM_TestCompound")
            for obj in mesh_objs:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = mesh_objs[0]

            res = bpy.ops.lod_tool.analyze_and_configure()
            self.assertEqual(res, {"FINISHED"})

            props = scene.lod_tool
            self.assertTrue(props.is_configured)
            self.assertGreater(props.bounding_radius, 0.0)
            self.assertGreater(props.base_triangles, 0)
            self.assertEqual(len(props.lods), props.lod_count)
            self.assertEqual(props.lods[0].screen_size_pct, 100.0)
            self.assertLess(props.lods[-1].screen_size_pct, props.lods[0].screen_size_pct)

    def test_generate_all_sibling_collections_and_isolation(self) -> None:
        """Verify generate_all creates sibling collections, unlinks from master, and isolates tiers."""
        with in_engine_sandbox() as scene:
            mesh_objs = create_hierarchy_fixture("SM_DagAsset")
            for obj in mesh_objs:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = mesh_objs[0]

            props = scene.lod_tool
            props.export_base_name = "SM_DagAsset"

            bpy.ops.lod_tool.analyze_and_configure()
            res = bpy.ops.lod_tool.generate_all()
            self.assertEqual(res, {"FINISHED"})

            # 1. Verify Root Collection Exists and Sibling Collections Exist
            root_coll = bpy.data.collections.get("SM_DagAsset")
            self.assertIsNotNone(root_coll, "Root collection 'SM_DagAsset' must be created.")
            lod1_coll = bpy.data.collections.get("SM_DagAsset_LOD1")
            lod2_coll = bpy.data.collections.get("SM_DagAsset_LOD2")
            lod3_coll = bpy.data.collections.get("SM_DagAsset_LOD3")
            self.assertIsNotNone(lod1_coll)
            self.assertIsNotNone(lod2_coll)
            self.assertIsNotNone(lod3_coll)

            # 2. Verify objects were unlinked from scene master collection
            for obj in mesh_objs:
                self.assertNotIn(obj.name, scene.collection.objects)
                self.assertIn(obj.name, root_coll.objects)

            # 3. Verify geometric reduction in sibling tiers
            lod0_tris = sum(len(o.data.polygons) for o in mesh_objs if o.type == "MESH")
            lod3_tris = sum(len(o.data.polygons) for o in lod3_coll.objects if o.type == "MESH")
            self.assertLess(lod3_tris, lod0_tris, "LOD3 triangle count must be significantly lower than LOD0.")

            # 4. Test Viewport Isolation via preview_tier
            bpy.ops.lod_tool.preview_tier(tier_index=1)
            self.assertTrue(root_coll.hide_viewport, "LOD0 must be hidden when previewing LOD1.")
            self.assertFalse(lod1_coll.hide_viewport, "LOD1 must be visible when previewing LOD1.")
            self.assertTrue(lod2_coll.hide_viewport, "LOD2 must be hidden when previewing LOD1.")

            # Reset preview
            bpy.ops.lod_tool.preview_tier(tier_index=-1)
            self.assertFalse(root_coll.hide_viewport, "All collections must be visible after reset.")
            self.assertFalse(lod1_coll.hide_viewport)

    def test_skinned_mesh_weight_clamping_and_shape_keys(self) -> None:
        """Verify rigged meshes have bone influences clamped to 4 and shape keys purged in distant tiers."""
        with in_engine_sandbox() as scene:
            mesh_obj, arm_obj = create_skinned_mesh("SM_SkinnedChar")
            bpy.context.view_layer.objects.active = mesh_obj
            mesh_obj.select_set(True)

            props = scene.lod_tool
            props.export_base_name = "SM_SkinnedChar"
            props.max_bone_influences = "4"
            props.purge_shape_keys = True

            bpy.ops.lod_tool.analyze_and_configure()
            res = bpy.ops.lod_tool.generate_all()
            self.assertEqual(res, {"FINISHED"})

            lod2_coll = bpy.data.collections.get("SM_SkinnedChar_LOD2")
            self.assertIsNotNone(lod2_coll)
            lod2_obj = next((o for o in lod2_coll.objects if o.type == "MESH"), None)
            self.assertIsNotNone(lod2_obj)

            # Verify bone influences clamped
            for v in lod2_obj.data.vertices:
                influences = [g for g in v.groups if g.weight > 1e-4]
                self.assertLessEqual(len(influences), 4, "Vertex influence must not exceed max_influences (4).")

            # Verify shape keys purged
            has_shape_keys = bool(lod2_obj.data.shape_keys and len(lod2_obj.data.shape_keys.key_blocks) > 0)
            self.assertFalse(has_shape_keys, "Shape keys must be purged at LOD2 when purge_shape_keys is True.")


if __name__ == "__main__":
    unittest.main()
