"""
Rigging, Weight Sanitization & Kinematic Bone Pruning Engine for LOD Tool.
"""

from __future__ import annotations

from contextlib import contextmanager
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


def normalize_weights_pure(
    weights: dict[int, float], max_influences: int = 4, micro_epsilon: float = 0.01, anchor_idx: int = 0
) -> dict[int, float]:
    """
    Pure algorithmic weight normalizer testable outside Blender.
    - Filters non-finite (NaN, Inf) and non-positive (<= 0.0) weights.
    - Drops weights < micro_epsilon.
    - Clamps to max_influences.
    - Normalizes sum strictly to 1.0 with rounding discrepancy absorption.
    - Protects against zero-sum / NaN singularities with anchor fallback.
    """
    if not weights or not isinstance(weights, dict):
        return {anchor_idx: 1.0}

    # Filter strictly finite and positive weights
    valid_raw: dict[int, float] = {}
    for idx, w in weights.items():
        if isinstance(idx, int) and isinstance(w, (int, float)) and math.isfinite(w) and w > 0.0:
            valid_raw[idx] = float(w)

    if not valid_raw:
        return {anchor_idx: 1.0}

    max_inf = max(1, int(max_influences))
    valid = [(idx, w) for idx, w in valid_raw.items() if w >= micro_epsilon]

    if not valid:
        # Fallback to the single highest non-zero weight if all drop below micro_epsilon
        best_idx = max(valid_raw.items(), key=lambda x: x[1])[0]
        return {best_idx: 1.0}

    valid.sort(key=lambda x: x[1], reverse=True)
    clamped = valid[:max_inf]

    weight_sum = sum(w for _, w in clamped)
    if weight_sum < 1e-6 or not math.isfinite(weight_sum):
        return {anchor_idx: 1.0}

    # Compute normalized weights
    result = {idx: round(w / weight_sum, 6) for idx, w in clamped}

    # Absorb any micro floating-point rounding discrepancy into top weight so sum == 1.0 exactly
    current_sum = sum(result.values())
    discrepancy = 1.0 - current_sum
    if abs(discrepancy) > 1e-7 and len(clamped) > 0:
        top_idx = clamped[0][0]
        result[top_idx] = round(result[top_idx] + discrepancy, 6)

    return result


@contextmanager
def armature_rest_pose_context(armature_obj: Any):
    """
    Context manager to safely lock an armature to REST pose during operations
    (decimation, normal transfer, mesh consolidation) and restore the original pose state.
    """
    if not armature_obj or not hasattr(armature_obj, "data") or not hasattr(armature_obj.data, "pose_position"):
        yield
        return

    orig_pose_pos = armature_obj.data.pose_position
    armature_obj.data.pose_position = "REST"
    try:
        yield
    finally:
        armature_obj.data.pose_position = orig_pose_pos


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
    """
    rest_world = armature_world @ bone_rest_local @ prop_parent_inverse @ prop_basis
    if target_mesh_rest_world is not None:
        return target_mesh_rest_world.inverted() @ rest_world
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
        """
        if not bpy or not bmesh or not obj or obj.type != "MESH" or len(obj.vertex_groups) == 0:
            return {"normalized": 0, "singularities_fixed": 0, "purged_vgs": 0}

        mesh = obj.data
        bm = bmesh.new()
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

        singularities_fixed = 0
        normalized_count = 0

        for vert in bm.verts:
            dvert = vert[dvert_lay]
            raw_weights = dict(dvert.items()) if dvert else {}

            cleaned = normalize_weights_pure(
                raw_weights, max_influences=max_influences, micro_epsilon=micro_weight_epsilon, anchor_idx=anchor_idx
            )

            if len(raw_weights) == 0 or (len(raw_weights) > 0 and sum(raw_weights.values()) < 1e-5):
                singularities_fixed += 1

            dvert.clear()
            for idx, w in cleaned.items():
                dvert[idx] = w

            normalized_count += 1

        bm.to_mesh(mesh)
        bm.free()
        mesh.update()

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
            obj.vertex_groups.remove(vg)
            purged_vg_count += 1

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
            or not hasattr(armature_obj, "data")
            or not hasattr(armature_obj.data, "bones")
        ):
            return 0

        vg_map = {vg.name: vg.index for vg in lod_obj.vertex_groups}
        mesh = lod_obj.data

        m_world = lod_obj.matrix_world
        vert_coords = [m_world @ v.co for v in mesh.vertices]

        bone_verts: dict[int, list[Any]] = {vg_idx: [] for vg_idx in vg_map.values()}
        for v in mesh.vertices:
            for g in v.groups:
                if g.weight > 0.01 and g.group in bone_verts:
                    bone_verts[g.group].append(vert_coords[v.index])

        bones = armature_obj.data.bones
        collapsed_bones: set[str] = set()

        changed = True
        total_collapsed = 0

        safe_dist = max(0.001, float(screen_distance_m))
        safe_fov = max(1e-4, float(fov_v_rad))

        while changed:
            changed = False
            for bone in bones:
                if bone.name in collapsed_bones or not bone.parent:
                    continue

                active_children = [c for c in bone.children if c.name not in collapsed_bones]
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

                angular_diameter = 2.0 * math.atan(radius / safe_dist)
                screen_px = (angular_diameter / safe_fov) * resolution_y

                if screen_px < pixel_threshold:
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
        if not bpy or not obj:
            return
        src_vg = obj.vertex_groups.get(source_name)
        if not src_vg:
            return

        tgt_vg = obj.vertex_groups.get(target_name)
        if not tgt_vg:
            tgt_vg = obj.vertex_groups.new(name=target_name)

        src_idx = src_vg.index
        tgt_idx = tgt_vg.index

        mesh = obj.data
        for v in mesh.vertices:
            src_weight = 0.0
            tgt_weight = 0.0
            for g in v.groups:
                if g.group == src_idx:
                    src_weight = g.weight
                elif g.group == tgt_idx:
                    tgt_weight = g.weight

            if src_weight > 0.0:
                tgt_vg.add([v.index], tgt_weight + src_weight, "REPLACE")
                src_vg.remove([v.index])
