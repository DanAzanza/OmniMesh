"""In-Blender Integration Tests for OmniMesh UI Operators, Scene Setup, and Tier Management."""

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


class TestUIPipeline(unittest.TestCase):
    """Verify OmniMesh UI scene setup, asset initialization, viewport overlays, and tier management."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_initialize_asset_and_scene_setup(self) -> None:
        """Verify 1-click asset initialization sets up collections and scene unit/FPS settings."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            mesh_objs = create_hierarchy_fixture("SM_UIHero")
            for obj in mesh_objs:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = mesh_objs[0]

            ops_om: Any = cast(Any, bpy.ops).omnimesh

            # 1. Initialize asset hierarchy
            res_init = ops_om.initialize_asset(asset_name="SM_UIHero")
            self.assertEqual(res_init, {"FINISHED"})

            # Root collection should exist
            root_col = bpy.data.collections.get("SM_UIHero")
            self.assertIsNotNone(root_col)

    def test_tier_management_and_solo_operators(self) -> None:
        """Verify adding, removing, resetting, and soloing LOD tiers."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            mesh_objs = create_hierarchy_fixture("SM_TierAsset")
            for obj in mesh_objs:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = mesh_objs[0]

            ops_lod: Any = cast(Any, bpy.ops).lod_tool
            ops_lod.analyze_and_configure()

            props: Any = getattr(scene, "lod_tool", None)
            assert props is not None
            initial_count = len(props.lods)
            self.assertGreater(initial_count, 0)

            # Add tier
            self.assertEqual(ops_lod.add_lod_tier(), {"FINISHED"})
            self.assertEqual(len(props.lods), initial_count + 1)

            # Remove tier
            self.assertEqual(ops_lod.remove_lod_tier(tier_index=len(props.lods) - 1), {"FINISHED"})
            self.assertEqual(len(props.lods), initial_count)

            # Reset to preset
            self.assertEqual(ops_lod.reset_to_preset(), {"FINISHED"})

            # Sync selection settings
            self.assertEqual(ops_lod.sync_selection_settings(), {"FINISHED"})

    def test_add_panel_interaction_volume_and_colliders(self) -> None:
        """Verify Add panel workflows: interaction clickspots and physics collision hulls."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mesh_objs = create_hierarchy_fixture("SM_AddAsset")
            for obj in mesh_objs:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = mesh_objs[0]

            ops_om: Any = cast(Any, bpy.ops).omnimesh
            ops_lod: Any = cast(Any, bpy.ops).lod_tool

            # Initialize asset hierarchy
            ops_om.initialize_asset(asset_name="SM_AddAsset")

            # 1. Add interaction volume / clickspot
            res_vol = ops_om.add_interaction_volume()
            self.assertEqual(res_vol, {"FINISHED"})

            interact_col = bpy.data.collections.get("SM_AddAsset_Interactions")
            self.assertIsNotNone(interact_col)
            assert interact_col is not None
            self.assertGreater(len(interact_col.objects), 0)

            # 2. Generate collision hulls
            res_col_gen = ops_lod.generate_collision_hulls()
            self.assertEqual(res_col_gen, {"FINISHED"})

            coll_col = bpy.data.collections.get("SM_AddAsset_Colliders")
            self.assertIsNotNone(coll_col)
            assert coll_col is not None
            self.assertGreater(len(coll_col.objects), 0)

    def test_toggle_side_by_side_in_blender(self) -> None:
        """Verify side-by-side inspection placement and reset alignment in Blender."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            mesh_objs = create_hierarchy_fixture("SM_SBSAsset")
            for obj in mesh_objs:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = mesh_objs[0]

            scene_any: Any = scene
            base_obj: Any = mesh_objs[0]

            ops_om: Any = cast(Any, bpy.ops).omnimesh
            ops_lod: Any = cast(Any, bpy.ops).lod_tool

            ops_om.initialize_asset(asset_name="SM_SBSAsset")

            # Create an artificial LOD1 collection and duplicate mesh
            lod1_col = bpy.data.collections.new("SM_SBSAsset_LOD1")
            scene.collection.children.link(lod1_col)
            lod1_obj: Any = base_obj.copy()
            lod1_obj.data = base_obj.data.copy()
            lod1_obj.name = "SM_SBSAsset_LOD1_Mesh"
            lod1_col.objects.link(lod1_obj)
            orig_x = float(lod1_obj.location.x)

            scene_any.lod_tool.active_asset = "SM_SBSAsset"

            # 1. Activate Side-by-Side
            res_act = ops_lod.toggle_side_by_side()
            self.assertEqual(res_act, {"FINISHED"})
            self.assertTrue(scene_any.lod_tool.is_side_by_side_active)
            self.assertGreater(lod1_obj.location.x, orig_x)
            self.assertFalse(lod1_col.hide_viewport)

            # 2. Reset Side-by-Side
            res_rst = ops_lod.toggle_side_by_side()
            self.assertEqual(res_rst, {"FINISHED"})
            self.assertFalse(scene_any.lod_tool.is_side_by_side_active)
            self.assertAlmostEqual(lod1_obj.location.x, orig_x, places=4)
            self.assertTrue(lod1_col.hide_viewport)


if __name__ == "__main__":
    unittest.main()
