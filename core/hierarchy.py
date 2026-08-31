"""
Hierarchy & Multi-Mesh Join Engine for LOD Tool.
"""

from __future__ import annotations

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


def get_rest_world_matrix_for_static(static_obj: Any, armature_obj: Any, bone_name: str) -> Any:
    """
    Computes the exact World Transform of a static object in the Armature's REST pose,
    bypassing any active Pose Mode or animation transformations.
    """
    if not armature_obj or not hasattr(armature_obj.data, "bones"):
        return static_obj.matrix_world.copy() if hasattr(static_obj, "matrix_world") else None

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
        using pure BMesh data pipelines (Zero bpy.ops calls, zero context dependencies).
        """
        if not bpy or not bmesh or not mesh_objs:
            return None

        # 1. Build Global Unified Material Palette
        global_materials: list[Any] = []
        mat_to_global_idx: dict[Any, int] = {}

        for obj in mesh_objs:
            for slot in obj.material_slots:
                mat = slot.material
                if mat and mat not in mat_to_global_idx:
                    mat_to_global_idx[mat] = len(global_materials)
                    global_materials.append(mat)

        # 2. Build Global Unified Vertex Group Palette
        global_vg_names: list[str] = []
        if armature_obj and hasattr(armature_obj.data, "bones"):
            global_vg_names = [b.name for b in armature_obj.data.bones]
        else:
            for obj in mesh_objs:
                for vg in obj.vertex_groups:
                    if vg.name not in global_vg_names:
                        global_vg_names.append(vg.name)

        vg_to_global_idx = {name: i for i, name in enumerate(global_vg_names)}

        # 3. Initialize Target Mesh and BMesh
        target_mesh_data = bpy.data.meshes.new(f"{output_obj_name}_Mesh")
        target_bm = bmesh.new()
        dvert_lay = target_bm.verts.layers.deform.verify()

        # 4. Process Each Source Object
        for obj in mesh_objs:
            local_mat_map: dict[int, int] = {}
            for loc_idx, slot in enumerate(obj.material_slots):
                if slot.material in mat_to_global_idx:
                    local_mat_map[loc_idx] = mat_to_global_idx[slot.material]
                else:
                    local_mat_map[loc_idx] = 0

            local_vg_map = {
                vg.index: vg_to_global_idx[vg.name] for vg in obj.vertex_groups if vg.name in vg_to_global_idx
            }

            parent_bone_name = obj.parent_bone if (obj.parent == armature_obj and obj.parent_type == "BONE") else None

            src_bm = bmesh.new()
            src_bm.from_mesh(obj.data)
            src_dvert = src_bm.verts.layers.deform.active

            if parent_bone_name and armature_obj:
                m_world = get_rest_world_matrix_for_static(obj, armature_obj, parent_bone_name)
            else:
                m_world = obj.matrix_world

            vert_map = {}
            for v in src_bm.verts:
                world_co = m_world @ v.co
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
                except ValueError:
                    pass

            src_bm.free()

        # 5. Write to Mesh Data Block
        target_bm.to_mesh(target_mesh_data)
        target_bm.free()
        target_mesh_data.update()

        # 6. Create Blender Object & Assign Materials/VGs
        merged_obj = bpy.data.objects.new(output_obj_name, target_mesh_data)
        for mat in global_materials:
            merged_obj.data.materials.append(mat)

        for vg_name in global_vg_names:
            merged_obj.vertex_groups.new(name=vg_name)

        if armature_obj:
            arm_mod = merged_obj.modifiers.new(name="Armature", type="ARMATURE")
            arm_mod.object = armature_obj

        return merged_obj
