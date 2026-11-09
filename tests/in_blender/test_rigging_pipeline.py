"""In-Blender Integration Tests for Skeletal Rigging, Weight Sanitization, and Deform Animation Baking."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any, cast
import unittest

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from tests.in_blender.fixtures import create_skinned_mesh, in_blender_sandbox
else:
    try:
        import bpy
        from tests.in_blender.fixtures import create_skinned_mesh, in_blender_sandbox
    except ImportError:
        bpy = None
        create_skinned_mesh = None  # type: ignore
        in_blender_sandbox = None  # type: ignore


class TestRiggingPipeline(unittest.TestCase):
    """Verify skeletal deformation pipelines, weight clamping, bone pruning, and animation baking in live Blender."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_weight_sanitizer_normalizes_and_clamps(self) -> None:
        """Verify WeightSanitizer clamps influences to max 4 and normalizes vertex group weights."""
        from core.rigging import WeightSanitizer

        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            mesh_obj, _ = create_skinned_mesh("SM_SkinTest")

            # Initially each vertex has 6 weights of 1/6
            res = WeightSanitizer.normalize_and_clamp_weights(mesh_obj, max_influences=4)
            self.assertTrue(res.get("normalized", 0) > 0)

            # Check that vertex weights on any vertex sum to ~1.0 and influences <= 4
            mesh: Any = mesh_obj.data
            for v in mesh.vertices:
                total_w = sum(g.weight for g in v.groups)
                self.assertAlmostEqual(total_w, 1.0, places=3)
                self.assertLessEqual(len(v.groups), 4)

    def test_kinematic_bone_pruning_and_bake_nla(self) -> None:
        """Verify KinematicBonePruner and AnimationRigSanitizer bake deform action and setup clean NLA."""
        from core.animations import AnimationRigSanitizer
        from core.rigging import KinematicBonePruner

        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return
            mesh_obj, arm_obj = create_skinned_mesh("SM_PruneTest")

            # Animate root bone
            arm_obj.animation_data_create()
            assert arm_obj.animation_data is not None
            action = bpy.data.actions.new(name="Action_TestRun")
            arm_obj.animation_data.action = action

            # Insert keyframe on armature
            arm_obj.keyframe_insert(data_path="location", frame=1)
            arm_obj.location.z = 1.0
            arm_obj.keyframe_insert(data_path="location", frame=10)

            # Prune kinematic subtrees for distant tier
            pruned = KinematicBonePruner.prune_kinematic_subtrees(
                lod_obj=mesh_obj,
                armature_obj=arm_obj,
                screen_distance_m=50.0,
                fov_v_rad=math.radians(60.0),
                resolution_y=1080,
                pixel_threshold=1.5,
            )
            self.assertIsInstance(pruned, int)

            # Bake deform animation
            baked = AnimationRigSanitizer.bake_deform_animation(
                context=bpy.context,
                source_armature=arm_obj,
                action=action,
                blend_data=bpy.data,
            )
            self.assertIsNotNone(baked)
            if baked:
                AnimationRigSanitizer.setup_clean_nla_export(arm_obj, baked)
                assert arm_obj.animation_data is not None
                self.assertIsNotNone(arm_obj.animation_data.nla_tracks)

            # Ensure active action is attached to armature for UI operator execution
            assert arm_obj.animation_data is not None
            arm_obj.animation_data.action = action
            bpy.context.view_layer.objects.active = arm_obj
            res = cast(Any, bpy.ops).lod_tool.bake_rig_animation()
            self.assertEqual(res, {"FINISHED"})


if __name__ == "__main__":
    unittest.main()
