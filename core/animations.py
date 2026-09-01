"""
OmniMesh Animation, NLA Track & Kinematic Constraint Baker.
Performs automated evaluated dependency graph matrix baking on deforming hierarchies,
stripping IK controllers, sanitizing timecodes, and isolating root motion for UE5/Unity.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    import bpy
    from mathutils import Matrix, Quaternion, Vector
except ImportError:
    bpy = None
    Matrix = None
    Quaternion = None
    Vector = None

logger = logging.getLogger(__name__)


def _safe_invert_matrix(mat: Any) -> Any:
    """Safely inverts a transform matrix, guarding against singular / zero-determinant matrices."""
    if mat is None:
        return None
    if hasattr(mat, "inverted"):
        try:
            if hasattr(mat, "determinant"):
                det = mat.determinant()
                if not math.isfinite(det) or abs(det) < 1e-8:
                    logger.warning("Singular matrix detected during animation inversion (det=%s). Returning copy.", det)
                    return mat.copy() if hasattr(mat, "copy") else mat
            return mat.inverted()
        except Exception as exc:
            logger.warning("Animation matrix inversion failed (%s). Returning copy.", exc)
            return mat.copy() if hasattr(mat, "copy") else mat
    return mat


class AnimationRigSanitizer:
    """Hardened Animation & Kinematic Rig Baker for Enterprise Game Engine Export."""

    @staticmethod
    def sanitize_action_name(name: str) -> str:
        """Sanitizes action names to conform with strict engine identifiers: ^[A-Za-z0-9_]+$."""
        if not name or not isinstance(name, str):
            return "Anim_Action"
        clean = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_")
        return clean or "Anim_Action"

    @classmethod
    def get_deform_bone_names(cls, armature: Any) -> List[str]:
        """Returns list of bone names marked for mesh deformation (`use_deform == True`)."""
        if not armature or getattr(armature, "type", None) != "ARMATURE":
            return []
        if not hasattr(armature, "data") or not hasattr(armature.data, "bones"):
            return []
        return [b.name for b in armature.data.bones if getattr(b, "use_deform", True)]

    @classmethod
    def get_action_fcurves(cls, action: Any) -> List[Any]:
        """Extracts all F-Curves from an Action, supporting legacy Actions and Blender 5.2+ Slotted/Layered Actions."""
        if not action:
            return []
        raw_fcurves = []
        if hasattr(action, "fcurves") and action.fcurves is not None:
            try:
                raw_fcurves.extend(list(action.fcurves))
            except Exception as exc:
                logger.debug("Legacy fcurves extraction skipped: %s", exc)
        if hasattr(action, "layers"):
            try:
                for layer in getattr(action, "layers", []):
                    for strip in getattr(layer, "strips", []):
                        for cb in getattr(strip, "channelbags", []):
                            if hasattr(cb, "fcurves") and cb.fcurves is not None:
                                raw_fcurves.extend(list(cb.fcurves))
            except Exception as exc:
                logger.debug("Layered fcurves extraction skipped: %s", exc)

        # Deduplicate while preserving order
        seen = set()
        unique_fcurves = []
        for fc in raw_fcurves:
            fc_id = id(fc)
            if fc_id not in seen:
                seen.add(fc_id)
                unique_fcurves.append(fc)
        return unique_fcurves

    @classmethod
    def create_action_fcurve(cls, action: Any, data_path: str, index: int, slot_name: str = "ArmatureSlot") -> Any:
        """Creates an FCurve on an Action, supporting both legacy Actions and Blender 5.2+ Slotted/Layered Actions."""
        if not action:
            return None

        # 1. Try legacy action.fcurves.new if available
        if hasattr(action, "fcurves") and action.fcurves is not None:
            try:
                return action.fcurves.new(data_path=data_path, index=index)
            except Exception as exc:
                logger.debug("action.fcurves.new failed, attempting layered fallback: %s", exc)

        # 2. Blender 5.2+ Slotted / Layered Actions fallback
        if hasattr(action, "layers") or hasattr(action, "slots"):
            try:
                slot = None
                if hasattr(action, "slots"):
                    if not action.slots:
                        try:
                            slot = action.slots.new(id_type="OBJECT", name=slot_name)
                        except TypeError:
                            try:
                                slot = action.slots.new(name=slot_name)
                            except TypeError:
                                slot = action.slots.new(slot_name)
                    else:
                        slot = action.slots[0]

                if not action.layers:
                    layer = action.layers.new(name="BaseLayer")
                else:
                    layer = action.layers[0]

                if not layer.strips:
                    strip = layer.strips.new(type="KEYFRAME")
                else:
                    strip = layer.strips[0]

                cb = None
                if hasattr(strip, "channelbag_for_slot") and slot:
                    cb = strip.channelbag_for_slot(slot)

                if not cb and hasattr(strip, "channelbags"):
                    for c in strip.channelbags:
                        if getattr(c, "slot", None) == slot or slot is None:
                            cb = c
                            break
                    if not cb:
                        if slot:
                            cb = strip.channelbags.new(slot=slot)
                        else:
                            cb = strip.channelbags.new()

                if cb and hasattr(cb, "fcurves"):
                    return cb.fcurves.new(data_path=data_path, index=index)
            except Exception as exc:
                logger.error("Failed to create slotted FCurve: %s", exc)

        return None

    @classmethod
    def validate_action_bounds(cls, action: Any) -> Dict[str, Any]:
        """Validates keyframe boundaries, subframe quantization, and frame bounds."""
        if not action:
            return {"valid": False, "error": "No action provided."}

        all_fcurves = cls.get_action_fcurves(action)
        fcurves = [fc for fc in all_fcurves if hasattr(fc, "keyframe_points") and len(fc.keyframe_points) > 0]
        if not fcurves:
            return {"valid": False, "error": "Action has no keyframes."}

        min_frames = []
        max_frames = []
        for fc in fcurves:
            try:
                r = fc.range()
                if math.isfinite(r[0]) and math.isfinite(r[1]):
                    min_frames.append(r[0])
                    max_frames.append(r[1])
            except Exception as exc:
                logger.debug("FCurve range extraction failed: %s", exc)

        if not min_frames or not max_frames:
            return {"valid": False, "error": "Action has invalid keyframe ranges."}

        start_frame_raw = min(min_frames)
        end_frame_raw = max(max_frames)

        subframe_keys = 0
        total_keys = 0

        for fc in fcurves:
            for kp in fc.keyframe_points:
                total_keys += 1
                co = getattr(kp, "co", None)
                if co is not None and hasattr(co, "x") and math.isfinite(co.x):
                    if abs(co.x - round(co.x)) > 1e-3:
                        subframe_keys += 1

        return {
            "valid": True,
            "start_frame": int(round(start_frame_raw)),
            "end_frame": int(round(end_frame_raw)),
            "start_frame_raw": float(start_frame_raw),
            "end_frame_raw": float(end_frame_raw),
            "total_keys": total_keys,
            "subframe_drift_keys": subframe_keys,
            "has_subframe_drift": subframe_keys > 0,
        }

    @classmethod
    def snap_action_to_integer_frames(cls, action: Any, drift_threshold: float = 0.5) -> int:
        """
        Detects and quantizes drifted subframe keyframes to exact integer frames.
        Adjusts bezier handles proportionally to preserve curve shapes and tangents.
        Returns the total number of snapped keyframe points.
        """
        if not action:
            return 0

        safe_threshold = (
            max(0.0, float(drift_threshold))
            if isinstance(drift_threshold, (int, float)) and math.isfinite(drift_threshold)
            else 0.5
        )

        all_fcurves = cls.get_action_fcurves(action)
        snapped_count = 0
        for fc in all_fcurves:
            if not hasattr(fc, "keyframe_points"):
                continue

            for kp in fc.keyframe_points:
                co = getattr(kp, "co", None)
                if co is None or not hasattr(co, "x") or not math.isfinite(co.x):
                    continue

                raw_x = co.x
                target_x = round(raw_x)
                dx = target_x - raw_x
                if abs(dx) > 1e-4 and abs(dx) <= safe_threshold:
                    if hasattr(kp, "handle_left") and hasattr(kp.handle_left, "x") and math.isfinite(kp.handle_left.x):
                        kp.handle_left.x += dx
                    if (
                        hasattr(kp, "handle_right")
                        and hasattr(kp.handle_right, "x")
                        and math.isfinite(kp.handle_right.x)
                    ):
                        kp.handle_right.x += dx
                    kp.co.x = float(target_x)
                    snapped_count += 1

            if hasattr(fc, "update"):
                try:
                    fc.update()
                except Exception as exc:
                    logger.debug("FCurve update failed: %s", exc)

        return snapped_count

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
        Guarantees timeline frame restoration, matrix singularity safety, and normalized rotation quaternions.
        """
        if not bpy or not context or not source_armature or not action:
            return None

        if getattr(source_armature, "type", None) != "ARMATURE":
            return None

        scene = getattr(context, "scene", None)
        if not scene:
            return None

        deform_bones = cls.get_deform_bone_names(source_armature)
        if not deform_bones:
            return None

        bounds = cls.validate_action_bounds(action)
        if not bounds["valid"]:
            return None

        # Bind action to armature
        if not source_armature.animation_data:
            source_armature.animation_data_create()
        source_armature.animation_data.action = action

        start_f = bounds["start_frame"]
        end_f = bounds["end_frame"]
        step = max(0.01, float(bake_step)) if isinstance(bake_step, (int, float)) and math.isfinite(bake_step) else 1.0

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
                curves[(b_name, "loc", i)] = cls.create_action_fcurve(baked_action, data_path=data_path_loc, index=i)
                curves[(b_name, "scale", i)] = cls.create_action_fcurve(
                    baked_action, data_path=data_path_scale, index=i
                )
            for i in range(4):
                curves[(b_name, "rot", i)] = cls.create_action_fcurve(baked_action, data_path=data_path_rot, index=i)

        orig_frame = scene.frame_current
        orig_subframe = getattr(scene, "frame_subframe", 0.0)

        try:
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

                    # Extract true matrix_basis (local channel transform relative to rest pose) with singularity guards
                    if pose_bone.parent:
                        parent_rest_inv = _safe_invert_matrix(pose_bone.parent.bone.matrix_local)
                        rest_local = (
                            parent_rest_inv @ pose_bone.bone.matrix_local if parent_rest_inv else Matrix.Identity(4)
                        )
                        parent_eval_rest = pose_bone.parent.matrix @ rest_local
                        parent_eval_rest_inv = _safe_invert_matrix(parent_eval_rest)
                        matrix_basis = (
                            parent_eval_rest_inv @ pose_bone.matrix if parent_eval_rest_inv else Matrix.Identity(4)
                        )
                    else:
                        root_rest_inv = _safe_invert_matrix(pose_bone.bone.matrix_local)
                        matrix_basis = root_rest_inv @ pose_bone.matrix if root_rest_inv else Matrix.Identity(4)

                    loc, rot, scale = matrix_basis.decompose()

                    # Finite-float and degenerate quaternion sanitization
                    rot_len_sq = (
                        (rot.w * rot.w + rot.x * rot.x + rot.y * rot.y + rot.z * rot.z) if hasattr(rot, "w") else 1.0
                    )
                    if not math.isfinite(rot_len_sq) or rot_len_sq < 1e-8:
                        if Quaternion:
                            rot = Quaternion((1.0, 0.0, 0.0, 0.0))
                    else:
                        rot.normalize()

                    # Sanitize location
                    safe_loc = [loc[i] if math.isfinite(loc[i]) else 0.0 for i in range(3)]
                    # Sanitize scale
                    safe_scale = [
                        scale[i] if math.isfinite(scale[i]) and abs(scale[i]) > 1e-6 else 1.0 for i in range(3)
                    ]
                    # Sanitize rotation
                    safe_rot = [rot[i] if math.isfinite(rot[i]) else (1.0 if i == 0 else 0.0) for i in range(4)]

                    # Add keyframe points
                    for i in range(3):
                        c_loc = curves.get((b_name, "loc", i))
                        if c_loc and hasattr(c_loc, "keyframe_points"):
                            c_loc.keyframe_points.insert(curr_f, safe_loc[i])
                        c_scale = curves.get((b_name, "scale", i))
                        if c_scale and hasattr(c_scale, "keyframe_points"):
                            c_scale.keyframe_points.insert(curr_f, safe_scale[i])
                    for i in range(4):
                        c_rot = curves.get((b_name, "rot", i))
                        if c_rot and hasattr(c_rot, "keyframe_points"):
                            c_rot.keyframe_points.insert(curr_f, safe_rot[i])

                curr_f += step
        finally:
            scene.frame_set(orig_frame, subframe=orig_subframe)

        return baked_action

    @classmethod
    def setup_clean_nla_export(cls, armature: Any, baked_action: Any) -> bool:
        """Pushes baked action to a pristine solo NLA track for FBX/glTF multi-engine export."""
        if not bpy or not armature or not baked_action:
            return False

        try:
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
            frame_range = getattr(baked_action, "frame_range", (1.0, 1.0))
            raw_start = frame_range[0] if (isinstance(frame_range, (list, tuple)) and len(frame_range) > 0) else 1.0
            start_frame = int(round(raw_start)) if math.isfinite(raw_start) else 1
            track.strips.new(getattr(baked_action, "name", "Action"), start_frame, baked_action)
            anim_data.action = None  # Ensure NLA evaluation takes precedence

            return True
        except Exception as exc:
            logger.error("Failed to setup clean NLA export: %s", exc)
            return False
