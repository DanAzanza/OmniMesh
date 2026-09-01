"""
Hierarchy & Multi-Mesh Join Engine for LOD Tool.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bmesh
    import bpy
    from mathutils import Matrix, Vector
except ImportError:
    bpy = None
    bmesh = None
    Matrix = None
    Vector = None


def get_rest_world_matrix_for_static(static_obj: Any, armature_obj: Any, bone_name: str) -> Any:
    """
    Computes the exact World Transform of a static object in the Armature's REST pose,
    bypassing any active Pose Mode or animation transformations.
    """
    if not static_obj or not hasattr(static_obj, "matrix_world"):
        return None

    if not armature_obj or not hasattr(armature_obj, "data") or not hasattr(armature_obj.data, "bones"):
        return static_obj.matrix_world.copy()

    bone = armature_obj.data.bones.get(bone_name)
    if not bone:
        return static_obj.matrix_world.copy()

    m_arm_world = armature_obj.matrix_world
    m_bone_rest_local = bone.matrix_local
    m_parent_inv = static_obj.matrix_parent_inverse
    m_basis = static_obj.matrix_basis

    return m_arm_world @ m_bone_rest_local @ m_parent_inv @ m_basis


class MeshMergeEngine:
    @staticmethod
    def consolidate_and_merge_meshes(
        mesh_objs: list[Any], output_obj_name: str, armature_obj: Any | None = None
    ) -> Any | None:
        """
        Merges multiple static and skinned meshes into a single optimized draw-call mesh
        using pure BMesh data pipelines (Zero bpy.ops calls, zero context dependencies),
        with complete preservation of UV channels, materials, smoothing, and vertex groups.
        """
        if not bpy or not bmesh:
            return None

        # Filter to valid mesh objects
        valid_objs = [
            obj for obj in mesh_objs if obj and getattr(obj, "type", "") == "MESH" and hasattr(obj, "data") and obj.data
        ]
        if not valid_objs:
            return None

        # 1. Build Global Unified Material Palette
        global_materials: list[Any] = []
        mat_to_global_idx: dict[Any, int] = {}

        for obj in valid_objs:
            for slot in obj.material_slots:
                mat = slot.material
                if mat and mat not in mat_to_global_idx:
                    mat_to_global_idx[mat] = len(global_materials)
                    global_materials.append(mat)

        # 2. Build Global Unified Vertex Group Palette
        global_vg_names: list[str] = []
        if armature_obj and hasattr(armature_obj, "data") and hasattr(armature_obj.data, "bones"):
            global_vg_names = [b.name for b in armature_obj.data.bones]
        else:
            for obj in valid_objs:
                for vg in obj.vertex_groups:
                    if vg.name not in global_vg_names:
                        global_vg_names.append(vg.name)

        vg_to_global_idx = {name: i for i, name in enumerate(global_vg_names)}

        # 3. Build Global Unified UV Palette
        global_uv_names: list[str] = []
        for obj in valid_objs:
            if hasattr(obj.data, "uv_layers"):
                for uv in obj.data.uv_layers:
                    if uv.name not in global_uv_names:
                        global_uv_names.append(uv.name)

        # 4. Initialize Target Mesh and BMesh
        target_mesh_data = bpy.data.meshes.new(f"{output_obj_name}_Mesh")
        target_bm = bmesh.new()

        try:
            dvert_lay = target_bm.verts.layers.deform.verify()

            # Ensure all global UV layers exist on target BMesh
            target_uv_layers = {}
            for uv_name in global_uv_names:
                target_uv_layers[uv_name] = target_bm.loops.layers.uv.new(uv_name)

            # 5. Process Each Source Object
            for obj in valid_objs:
                local_mat_map: dict[int, int] = {}
                for loc_idx, slot in enumerate(obj.material_slots):
                    if slot.material in mat_to_global_idx:
                        local_mat_map[loc_idx] = mat_to_global_idx[slot.material]
                    else:
                        local_mat_map[loc_idx] = 0

                local_vg_map = {
                    vg.index: vg_to_global_idx[vg.name] for vg in obj.vertex_groups if vg.name in vg_to_global_idx
                }

                parent_bone_name = (
                    obj.parent_bone
                    if (obj.parent == armature_obj and getattr(obj, "parent_type", "") == "BONE")
                    else None
                )

                src_bm = bmesh.new()
                try:
                    src_bm.from_mesh(obj.data)
                    src_dvert = src_bm.verts.layers.deform.active

                    if parent_bone_name and armature_obj:
                        m_world = get_rest_world_matrix_for_static(obj, armature_obj, parent_bone_name)
                    else:
                        m_world = obj.matrix_world

                    if m_world is None:
                        m_world = Matrix.Identity(4) if Matrix else None

                    vert_map = {}
                    for v in src_bm.verts:
                        world_co = (m_world @ v.co) if m_world else v.co.copy()
                        new_v = target_bm.verts.new(world_co)
                        dvert = new_v[dvert_lay]

                        if src_dvert and v[src_dvert]:
                            for loc_vg_idx, weight in v[src_dvert].items():
                                if loc_vg_idx in local_vg_map:
                                    dvert[local_vg_map[loc_vg_idx]] = weight
                        elif parent_bone_name and parent_bone_name in vg_to_global_idx:
                            dvert[vg_to_global_idx[parent_bone_name]] = 1.0

                        vert_map[v] = new_v

                    target_bm.verts.ensure_lookup_table()

                    for f in src_bm.faces:
                        try:
                            new_f = target_bm.faces.new([vert_map[v] for v in f.verts])
                            new_f.material_index = local_mat_map.get(f.material_index, 0)
                            new_f.smooth = f.smooth

                            # Transfer UV coordinates across matching layers
                            for uv_name, src_uv in src_bm.loops.layers.uv.items():
                                tgt_uv = target_uv_layers.get(uv_name)
                                if tgt_uv:
                                    for src_lp, tgt_lp in zip(f.loops, new_f.loops, strict=False):
                                        tgt_lp[tgt_uv].uv = src_lp[src_uv].uv.copy()
                        except ValueError as exc:
                            logger.debug("Face merge error: %s", exc)
                finally:
                    src_bm.free()

            # 6. Write to Mesh Data Block
            target_bm.to_mesh(target_mesh_data)
        finally:
            target_bm.free()

        target_mesh_data.update()

        # 7. Create Blender Object & Assign Materials/VGs
        merged_obj = bpy.data.objects.new(output_obj_name, target_mesh_data)
        for mat in global_materials:
            merged_obj.data.materials.append(mat)

        for vg_name in global_vg_names:
            merged_obj.vertex_groups.new(name=vg_name)

        if armature_obj:
            arm_mod = merged_obj.modifiers.new(name="Armature", type="ARMATURE")
            arm_mod.object = armature_obj

        return merged_obj
