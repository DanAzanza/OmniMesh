"""
Rigging, Weight Sanitization & Kinematic Bone Pruning Engine for LOD Tool.
"""

from __future__ import annotations

from contextlib import contextmanager
import logging
import math
from typing import Any

try:
    import bmesh
    import bpy
    from mathutils import Matrix, Vector
except ImportError:
    bpy = None
    bmesh = None
    Matrix = None
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
                    logger.warning("Singular matrix detected in inversion (det=%s). Returning fallback copy.", det)
                    return mat.copy() if hasattr(mat, "copy") else mat
            return mat.inverted()
        except Exception as exc:
            logger.warning("Matrix inversion failed (%s). Returning fallback copy.", exc)
            return mat.copy() if hasattr(mat, "copy") else mat
    return mat


def normalize_weights_pure(
    weights: dict[int, float], max_influences: int = 4, micro_epsilon: float = 0.01, anchor_idx: int = 0
) -> dict[int, float]:
    """
    Pure algorithmic weight normalizer testable outside Blender.
    - Filters non-finite (NaN, Inf), negative indices, and non-positive (<= 0.0) weights.
    - Drops weights < micro_epsilon.
    - Clamps to max_influences.
    - Normalizes sum strictly to 1.0 with rounding discrepancy absorption.
    - Protects against zero-sum / NaN singularities with anchor fallback.
    """
    # Defensive sanitization of anchor index
    safe_anchor_idx = (
        int(anchor_idx)
        if isinstance(anchor_idx, (int, float)) and math.isfinite(anchor_idx) and int(anchor_idx) >= 0
        else 0
    )

    if not weights or not isinstance(weights, dict):
        return {safe_anchor_idx: 1.0}

    # Defensive sanitization of parameters
    try:
        if isinstance(max_influences, (int, float)) and math.isfinite(max_influences):
            max_inf = max(1, int(max_influences))
        else:
            max_inf = 4
    except (TypeError, ValueError):
        max_inf = 4

    try:
        if isinstance(micro_epsilon, (int, float)) and math.isfinite(micro_epsilon):
            safe_epsilon = max(0.0, float(micro_epsilon))
        else:
            safe_epsilon = 0.01
    except (TypeError, ValueError):
        safe_epsilon = 0.01

    # Filter strictly finite, valid index (>= 0), and positive weights
    valid_raw: dict[int, float] = {}
    for idx, w in weights.items():
        if isinstance(idx, int) and idx >= 0 and isinstance(w, (int, float)) and math.isfinite(w) and w > 0.0:
            valid_raw[idx] = float(w)

    if not valid_raw:
        return {safe_anchor_idx: 1.0}

    valid = [(idx, w) for idx, w in valid_raw.items() if w >= safe_epsilon]

    if not valid:
        # Fallback to the single highest non-zero weight if all drop below micro_epsilon
        best_idx = max(valid_raw.items(), key=lambda x: x[1])[0]
        return {best_idx: 1.0}

    valid.sort(key=lambda x: x[1], reverse=True)
    clamped = valid[:max_inf]

    weight_sum = sum(w for _, w in clamped)
    if weight_sum < 1e-6 or not math.isfinite(weight_sum):
        return {safe_anchor_idx: 1.0}

    # Compute normalized weights
    result = {idx: round(w / weight_sum, 6) for idx, w in clamped}

    # Absorb any micro floating-point rounding discrepancy into top weight so sum == 1.0 exactly
    current_sum = sum(result.values())
    discrepancy = round(1.0 - current_sum, 6)
    if abs(discrepancy) > 1e-7 and len(clamped) > 0:
        top_idx = clamped[0][0]
        result[top_idx] = max(0.0, min(1.0, round(result[top_idx] + discrepancy, 6)))

    # Guarantee non-empty and valid sum
    final_sum = sum(result.values())
    if not math.isfinite(final_sum) or final_sum < 1e-6:
        return {safe_anchor_idx: 1.0}

    return result


@contextmanager
def armature_rest_pose_context(armature_obj: Any):
    """
    Context manager to safely lock an armature to REST pose during operations
    (decimation, normal transfer, mesh consolidation) and restore the original pose state.
    """
    data = getattr(armature_obj, "data", None) if armature_obj else None
    if not data or not hasattr(data, "pose_position"):
        yield
        return

    orig_pose_pos = getattr(data, "pose_position", "POSE")
    try:
        data.pose_position = "REST"
    except Exception as exc:
        logger.warning("Failed to set armature to REST pose: %s", exc)

    try:
        yield
    finally:
        try:
            if armature_obj and getattr(armature_obj, "data", None):
                armature_obj.data.pose_position = orig_pose_pos
        except Exception as exc:
            logger.debug("Failed to restore armature pose position: %s", exc)


def compute_rest_pose_inverted_matrix(
    armature_world: Any,
    bone_rest_local: Any,
    prop_parent_inverse: Any,
    prop_basis: Any,
    target_mesh_rest_world: Any = None,
) -> Any:
    """
    Computes the exact World/Local Transform of a static object in the Armature's REST pose.
    M_{S -> M_rest} = M_{M_rest_world}^-1 @ M_{Arm_world} @ M_{B_bone_local} @ M_{S_parent_inv} @ M_{S_basis}
    Guarantees matrix math safety against non-invertible / singular matrices.
    """
    if armature_world is None or bone_rest_local is None or prop_parent_inverse is None or prop_basis is None:
        return target_mesh_rest_world or armature_world

    try:
        rest_world = armature_world @ bone_rest_local @ prop_parent_inverse @ prop_basis
    except Exception as exc:
        logger.error("Matrix multiplication failed in compute_rest_pose_inverted_matrix: %s", exc)
        return target_mesh_rest_world or armature_world

    if target_mesh_rest_world is not None:
        inverted_target = _safe_invert_matrix(target_mesh_rest_world)
        if inverted_target is not None:
            try:
                return inverted_target @ rest_world
            except Exception as exc:
                logger.error("Failed to multiply inverted target mesh matrix: %s", exc)
                return rest_world
        return rest_world

    return rest_world


class WeightSanitizer:
    @staticmethod
    def normalize_and_clamp_weights(
        obj: Any, max_influences: int = 4, micro_weight_epsilon: float = 0.01, anchor_vg_name: str = "Root"
    ) -> dict[str, int]:
        """
        Hardens vertex weights for GPU skinning:
        - Clamps max influences per vertex (4 for mobile/glTF, 8 for UE5/Unity).
        - Prunes micro-weights (< epsilon).
        - Enforces strict sum(w) = 1.0.
        - Guarantees NO zero-sum / NaN singularities by falling back to anchor bone.
        - Safely purges unused vertex groups by name to prevent index-shift corruption.
        - Guarantees BMesh memory safety via try...finally block.
        """
        if (
            not bpy
            or not bmesh
            or not obj
            or getattr(obj, "type", None) != "MESH"
            or not hasattr(obj, "vertex_groups")
            or len(obj.vertex_groups) == 0
            or not getattr(obj, "data", None)
            or not hasattr(obj.data, "vertices")
            or len(obj.data.vertices) == 0
        ):
            return {"normalized": 0, "singularities_fixed": 0, "purged_vgs": 0}

        mesh = obj.data
        bm = bmesh.new()
        singularities_fixed = 0
        normalized_count = 0

        try:
            bm.from_mesh(mesh)
            dvert_lay = bm.verts.layers.deform.verify()

            # Find or fallback anchor vertex group
            anchor_vg = obj.vertex_groups.get(anchor_vg_name)
            if not anchor_vg and anchor_vg_name:
                for vg in obj.vertex_groups:
                    if vg.name.lower() == anchor_vg_name.lower():
                        anchor_vg = vg
                        break
            if not anchor_vg and len(obj.vertex_groups) > 0:
                anchor_vg = obj.vertex_groups[0]

            anchor_idx = anchor_vg.index if anchor_vg else 0
            vg_count = len(obj.vertex_groups)

            for vert in bm.verts:
                dvert = vert[dvert_lay]
                raw_weights = dict(dvert.items()) if dvert else {}

                # Filter out raw weights pointing to out-of-bounds group indices
                sanitized_raw = {k: v for k, v in raw_weights.items() if 0 <= k < vg_count}

                cleaned = normalize_weights_pure(
                    sanitized_raw,
                    max_influences=max_influences,
                    micro_epsilon=micro_weight_epsilon,
                    anchor_idx=anchor_idx,
                )

                if len(sanitized_raw) == 0 or (len(sanitized_raw) > 0 and sum(sanitized_raw.values()) < 1e-5):
                    singularities_fixed += 1

                if dvert is not None:
                    dvert.clear()
                    for idx, w in cleaned.items():
                        if 0 <= idx < vg_count:
                            dvert[idx] = w

                normalized_count += 1

            bm.to_mesh(mesh)
            mesh.update()
        except Exception as exc:
            logger.error("Weight normalization failed on '%s': %s", getattr(obj, "name", "unknown"), exc)
        finally:
            bm.free()

        # Safely determine which vertex group names are actually used across all vertices (including loose/edges)
        used_vg_names: set[str] = set()
        vg_count = len(obj.vertex_groups)
        for v in mesh.vertices:
            for g in v.groups:
                if g.weight > 0.0001 and 0 <= g.group < vg_count:
                    used_vg_names.add(obj.vertex_groups[g.group].name)

        # Collect unused vertex groups first, then safely remove by reference
        purged_vg_count = 0
        to_purge = [vg for vg in list(obj.vertex_groups) if vg.name not in used_vg_names]
        for vg in to_purge:
            try:
                obj.vertex_groups.remove(vg)
                purged_vg_count += 1
            except Exception as exc:
                logger.debug("Failed to remove unused vertex group '%s': %s", getattr(vg, "name", "unknown"), exc)

        return {
            "normalized": normalized_count,
            "singularities_fixed": singularities_fixed,
            "purged_vgs": purged_vg_count,
        }


class KinematicBonePruner:
    @classmethod
    def prune_kinematic_subtrees(
        cls,
        lod_obj: Any,
        armature_obj: Any,
        screen_distance_m: float,
        fov_v_rad: float,
        resolution_y: int,
        pixel_threshold: float = 1.5,
    ) -> int:
        """
        Recursively walks the bone hierarchy from leaves upwards.
        Collapses bones whose vertex bounding sphere screen diameter < pixel_threshold
        into their immediate parent bone.
        """
        if (
            not bpy
            or not lod_obj
            or not armature_obj
            or getattr(lod_obj, "type", None) != "MESH"
            or not getattr(lod_obj, "data", None)
            or not hasattr(lod_obj.data, "vertices")
            or len(lod_obj.data.vertices) == 0
            or not hasattr(armature_obj, "data")
            or not hasattr(armature_obj.data, "bones")
            or len(armature_obj.data.bones) == 0
        ):
            return 0

        vg_map = {vg.name: vg.index for vg in getattr(lod_obj, "vertex_groups", [])}
        mesh = lod_obj.data

        m_world = getattr(lod_obj, "matrix_world", None)
        if m_world is not None:
            vert_coords = [m_world @ v.co for v in mesh.vertices]
        else:
            vert_coords = [v.co for v in mesh.vertices]

        bone_verts: dict[int, list[Any]] = {vg_idx: [] for vg_idx in vg_map.values()}
        for v in mesh.vertices:
            for g in v.groups:
                if g.weight > 0.01 and g.group in bone_verts:
                    bone_verts[g.group].append(vert_coords[v.index])

        bones = armature_obj.data.bones
        collapsed_bones: set[str] = set()

        changed = True
        total_collapsed = 0

        safe_dist = (
            max(0.001, float(screen_distance_m))
            if isinstance(screen_distance_m, (int, float)) and math.isfinite(screen_distance_m)
            else 10.0
        )
        safe_fov = (
            max(1e-4, float(fov_v_rad))
            if isinstance(fov_v_rad, (int, float)) and math.isfinite(fov_v_rad)
            else math.radians(60.0)
        )
        safe_res_y = (
            max(1, int(resolution_y))
            if isinstance(resolution_y, (int, float)) and math.isfinite(resolution_y)
            else 1080
        )
        safe_thresh = (
            max(0.0, float(pixel_threshold))
            if isinstance(pixel_threshold, (int, float)) and math.isfinite(pixel_threshold)
            else 1.5
        )

        while changed:
            changed = False
            for bone in bones:
                if bone.name in collapsed_bones or not getattr(bone, "parent", None):
                    continue

                active_children = [c for c in getattr(bone, "children", []) if c.name not in collapsed_bones]
                if len(active_children) > 0:
                    continue

                vg_idx = vg_map.get(bone.name)
                assigned_coords = bone_verts.get(vg_idx, []) if vg_idx is not None else []

                if not assigned_coords:
                    collapsed_bones.add(bone.name)
                    changed = True
                    continue

                zero_vec = Vector((0.0, 0.0, 0.0)) if Vector else None
                if zero_vec is not None:
                    center = sum(assigned_coords, zero_vec) / len(assigned_coords)
                    radius = max((co - center).length for co in assigned_coords)
                else:
                    center = sum(assigned_coords) / len(assigned_coords)
                    radius = max(abs(co - center) for co in assigned_coords)

                if not math.isfinite(radius) or radius < 0.0:
                    radius = 0.0

                angular_diameter = 2.0 * math.atan(radius / safe_dist)
                screen_px = (angular_diameter / safe_fov) * safe_res_y

                if screen_px < safe_thresh:
                    parent_name = bone.parent.name
                    cls._transfer_weights(lod_obj, source_name=bone.name, target_name=parent_name)
                    # Update bone_verts and vg_map for hierarchy continuity
                    parent_vg = lod_obj.vertex_groups.get(parent_name)
                    if parent_vg:
                        parent_idx = parent_vg.index
                        vg_map[parent_name] = parent_idx
                        if parent_idx not in bone_verts:
                            bone_verts[parent_idx] = []
                        if vg_idx is not None and vg_idx in bone_verts:
                            bone_verts[parent_idx].extend(bone_verts[vg_idx])
                            bone_verts[vg_idx] = []
                    collapsed_bones.add(bone.name)
                    total_collapsed += 1
                    changed = True

        return total_collapsed

    @staticmethod
    def _transfer_weights(obj: Any, source_name: str, target_name: str):
        if not bpy or not obj or not getattr(obj, "data", None):
            return
        src_vg = obj.vertex_groups.get(source_name)
        if not src_vg:
            return

        tgt_vg = obj.vertex_groups.get(target_name)
        if not tgt_vg:
            try:
                tgt_vg = obj.vertex_groups.new(name=target_name)
            except Exception as exc:
                logger.error("Failed to create vertex group '%s': %s", target_name, exc)
                return

        src_idx = src_vg.index
        tgt_idx = tgt_vg.index

        mesh = obj.data
        for v in getattr(mesh, "vertices", []):
            src_weight = 0.0
            tgt_weight = 0.0
            for g in v.groups:
                if g.group == src_idx:
                    src_weight = g.weight
                elif g.group == tgt_idx:
                    tgt_weight = g.weight

            if src_weight > 0.0:
                combined_weight = min(1.0, max(0.0, tgt_weight + src_weight))
                tgt_vg.add([v.index], combined_weight, "REPLACE")
                src_vg.remove([v.index])
