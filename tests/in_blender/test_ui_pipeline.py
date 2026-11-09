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

            # 2. Quick scene setup (60 FPS, Metric, Clip)
            res_setup = ops_om.quick_scene_setup()
            self.assertEqual(res_setup, {"FINISHED"})
            self.assertEqual(scene.render.fps, 60)
            self.assertEqual(scene.unit_settings.system, "METRIC")

            # 3. Viewport overlay toggles
            res_overlay = ops_om.toggle_viewport_overlay(mode="STATS")
            self.assertEqual(res_overlay, {"FINISHED"})

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

            # Solo and un-solo tier
            self.assertEqual(ops_lod.solo_tier(tier_index=0), {"FINISHED"})
            self.assertEqual(ops_lod.solo_tier(tier_index=-1), {"FINISHED"})

            # Sync selection settings
            self.assertEqual(ops_lod.sync_selection_settings(), {"FINISHED"})


if __name__ == "__main__":
    unittest.main()
