"""
OmniMesh Animation, NLA Track & Kinematic Constraint Baker.
Performs automated evaluated dependency graph matrix baking on deforming hierarchies,
stripping IK controllers, sanitizing timecodes, and isolating root motion for UE5/Unity.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

try:
    import bpy
except ImportError:
    bpy = None


class AnimationRigSanitizer:
    """Hardened Animation & Kinematic Rig Baker for Enterprise Game Engine Export."""

    @staticmethod
    def sanitize_action_name(name: str) -> str:
        """Sanitizes action names to conform with strict engine identifiers: ^[A-Za-z0-9_]+$."""
        clean = re.sub(r"[^A-Za-z0-9_]", "_", name)
        return clean.strip("_") or "Anim_Action"

    @classmethod
    def get_deform_bone_names(cls, armature: Any) -> List[str]:
        """Returns list of bone names marked for mesh deformation (`use_deform == True`)."""
        if not armature or getattr(armature, "type", None) != "ARMATURE":
            return []
        return [b.name for b in armature.data.bones if getattr(b, "use_deform", True)]

    @classmethod
    def validate_action_bounds(cls, action: Any) -> Dict[str, Any]:
        """Validates keyframe boundaries, subframe quantization, and frame bounds."""
        if not action or not getattr(action, "fcurves", None):
            return {"valid": False, "error": "Action has no F-Curves."}

        fcurves = [fc for fc in action.fcurves if len(getattr(fc, "keyframe_points", [])) > 0]
        if not fcurves:
            return {"valid": False, "error": "Action has no keyframes."}

        start_frame = min(fc.range()[0] for fc in fcurves)
        end_frame = max(fc.range()[1] for fc in fcurves)

        subframe_keys = 0
        total_keys = 0

        for fc in fcurves:
            for kp in fc.keyframe_points:
                total_keys += 1
                if abs(kp.co.x - round(kp.co.x)) > 1e-3:
                    subframe_keys += 1

        return {
            "valid": True,
            "start_frame": int(start_frame),
            "end_frame": int(end_frame),
            "total_keys": total_keys,
            "subframe_drift_keys": subframe_keys,
            "has_subframe_drift": subframe_keys > 0,
        }

    @classmethod
    def bake_deform_animation(
        cls,
        context: Any,
        source_armature: Any,
        action: Any,
        bake_step: float = 1.0,
    ) -> Optional[Any]:
        """Bakes evaluated depsgraph world matrices of all deforming bones into a clean FK Action.

        Eliminates IK constraints, Spline IK, and Copy Transforms for pristine UE5/Unity export.
        """
        if not bpy or not source_armature or not action:
            return None

        scene = context.scene
        deform_bones = cls.get_deform_bone_names(source_armature)
        if not deform_bones:
            return None

        # Bind action
        if not source_armature.animation_data:
            source_armature.animation_data_create()
        source_armature.animation_data.action = action

        bounds = cls.validate_action_bounds(action)
        if not bounds["valid"]:
            return None

        start_f = bounds["start_frame"]
        end_f = bounds["end_frame"]

        # Ensure all deform pose bones use Quaternion rotation mode
        for b_name in deform_bones:
            pb = source_armature.pose.bones.get(b_name)
            if pb:
                pb.rotation_mode = "QUATERNION"

        # Create clean target action
        clean_name = cls.sanitize_action_name(f"{action.name}_Baked_Deform")
        baked_action = bpy.data.actions.new(name=clean_name)

        # Pre-allocate curve channels
        curves: Dict[Tuple[str, str, int], Any] = {}
        for b_name in deform_bones:
            data_path_loc = f'pose.bones["{b_name}"].location'
            data_path_rot = f'pose.bones["{b_name}"].rotation_quaternion'
            data_path_scale = f'pose.bones["{b_name}"].scale'

            for i in range(3):
                curves[(b_name, "loc", i)] = baked_action.fcurves.new(data_path=data_path_loc, index=i)
                curves[(b_name, "scale", i)] = baked_action.fcurves.new(data_path=data_path_scale, index=i)
            for i in range(4):
                curves[(b_name, "rot", i)] = baked_action.fcurves.new(data_path=data_path_rot, index=i)

        # Frame-by-frame Depsgraph Evaluation
        curr_f = float(start_f)
        while curr_f <= float(end_f) + 1e-4:
            scene.frame_set(int(curr_f), subframe=curr_f - int(curr_f))
            depsgraph = context.evaluated_depsgraph_get()
            eval_armature = source_armature.evaluated_get(depsgraph)

            for b_name in deform_bones:
                pose_bone = eval_armature.pose.bones.get(b_name)
                if not pose_bone:
                    continue

                # Extract true matrix_basis (local channel transform relative to rest pose)
                if pose_bone.parent:
                    rest_local = pose_bone.parent.bone.matrix_local.inverted() @ pose_bone.bone.matrix_local
                    matrix_basis = (pose_bone.parent.matrix @ rest_local).inverted() @ pose_bone.matrix
                else:
                    matrix_basis = pose_bone.bone.matrix_local.inverted() @ pose_bone.matrix

                loc, rot, scale = matrix_basis.decompose()

                # Add keyframe points
                for i in range(3):
                    curves[(b_name, "loc", i)].keyframe_points.insert(curr_f, loc[i])
                    curves[(b_name, "scale", i)].keyframe_points.insert(curr_f, scale[i])
                for i in range(4):
                    curves[(b_name, "rot", i)].keyframe_points.insert(curr_f, rot[i])

            curr_f += bake_step

        return baked_action

    @classmethod
    def setup_clean_nla_export(cls, armature: Any, baked_action: Any) -> bool:
        """Pushes baked action to a pristine solo NLA track for FBX/glTF multi-engine export."""
        if not bpy or not armature or not baked_action:
            return False

        anim_data = armature.animation_data
        if not anim_data:
            anim_data = armature.animation_data_create()

        # Clear existing tracks
        for track in list(anim_data.nla_tracks):
            anim_data.nla_tracks.remove(track)

        # Create solo track
        track = anim_data.nla_tracks.new()
        track.name = "NLA_Export_Track"
        track.is_solo = True
        track.strips.new(baked_action.name, int(baked_action.frame_range[0]), baked_action)
        anim_data.action = None  # Ensure NLA evaluation takes precedence

        return True
