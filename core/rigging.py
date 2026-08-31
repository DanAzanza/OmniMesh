"""
Rigging, Weight Sanitization & Kinematic Bone Pruning Engine for LOD Tool.
"""

from __future__ import annotations

import math
from typing import Any

try:
    import bmesh
    import bpy
    from mathutils import Vector
except ImportError:
    bpy = None
    bmesh = None
    Vector = None


def normalize_weights_pure(
    weights: dict[int, float], max_influences: int = 4, micro_epsilon: float = 0.01, anchor_idx: int = 0
) -> dict[int, float]:
    """
    Pure algorithmic weight normalizer testable outside Blender.
    - Drops weights < micro_epsilon.
    - Clamps to max_influences.
    - Normalizes sum to 1.0.
    - Protects against zero-sum / NaN singularities with anchor fallback.
    """
    if not weights:
        return {anchor_idx: 1.0}

    valid = [(idx, w) for idx, w in weights.items() if w >= micro_epsilon]

    if not valid:
        best_idx = max(weights.items(), key=lambda x: x[1])[0]
        return {best_idx: 1.0}

    valid.sort(key=lambda x: x[1], reverse=True)
    clamped = valid[:max_influences]

    weight_sum = sum(w for _, w in clamped)
    if weight_sum < 1e-6:
        return {anchor_idx: 1.0}

    return {idx: round(w / weight_sum, 6) for idx, w in clamped}


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

        anchor_vg = obj.vertex_groups.get(anchor_vg_name)
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

        # Safely determine which vertex group names are actually used
        used_vg_names: set[str] = set()
        for poly in mesh.polygons:
            for v_idx in poly.vertices:
                v = mesh.vertices[v_idx]
                for g in v.groups:
                    if g.weight > 0.001 and g.group < len(obj.vertex_groups):
                        used_vg_names.add(obj.vertex_groups[g.group].name)

        purged_vg_count = 0
        for vg in list(obj.vertex_groups):
            if vg.name not in used_vg_names:
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
        if not bpy or not lod_obj or not armature_obj or not hasattr(armature_obj.data, "bones"):
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

        while changed:
            changed = False
            for bone in bones:
                if bone.name in collapsed_bones or not bone.parent:
                    continue

                active_children = [c for c in bone.children if c.name not in collapsed_bones]
                if len(active_children) > 0:
                    continue

                vg_idx = vg_map.get(bone.name)
                assigned_coords = bone_verts.get(vg_idx, [])

                if not assigned_coords:
                    collapsed_bones.add(bone.name)
                    changed = True
                    continue

                center = sum(assigned_coords, Vector()) / len(assigned_coords)
                radius = max((co - center).length for co in assigned_coords)

                angular_diameter = 2.0 * math.atan(radius / max(0.001, screen_distance_m))
                screen_px = (angular_diameter / fov_v_rad) * resolution_y

                if screen_px < pixel_threshold:
                    parent_name = bone.parent.name
                    cls._transfer_weights(lod_obj, source_name=bone.name, target_name=parent_name)
                    collapsed_bones.add(bone.name)
                    total_collapsed += 1
                    changed = True

        return total_collapsed

    @staticmethod
    def _transfer_weights(obj: Any, source_name: str, target_name: str):
        if not bpy or not obj:
            return
        src_vg = obj.vertex_groups.get(source_name)
        tgt_vg = obj.vertex_groups.get(target_name)
        if not src_vg or not tgt_vg:
            return

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
