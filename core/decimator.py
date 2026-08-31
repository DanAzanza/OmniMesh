"""
Decimation and Simplification Engine for OmniMesh.
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


class MeshDecimator:
    @staticmethod
    def tag_boundaries_and_uv_seams(bm: Any) -> set[int]:
        pinned_vert_indices: set[int] = set()
        if not bmesh or not bm:
            return pinned_vert_indices

        # Tag Open Geometric Boundaries
        for edge in bm.edges:
            if edge.is_boundary:
                pinned_vert_indices.add(edge.verts[0].index)
                pinned_vert_indices.add(edge.verts[1].index)

        # Tag Sharp Marks & Seam Edges
        for edge in bm.edges:
            if edge.seam or not edge.smooth:
                pinned_vert_indices.add(edge.verts[0].index)
                pinned_vert_indices.add(edge.verts[1].index)

        # Tag Material Boundaries
        for edge in bm.edges:
            if len(edge.link_faces) == 2:
                if edge.link_faces[0].material_index != edge.link_faces[1].material_index:
                    pinned_vert_indices.add(edge.verts[0].index)
                    pinned_vert_indices.add(edge.verts[1].index)

        # Tag UV Seams across Face Loops
        uv_layer = bm.loops.layers.uv.active
        for edge in bm.edges:
            if len(edge.link_faces) == 2:
                f1, f2 = edge.link_faces[0], edge.link_faces[1]
                if uv_layer:
                    loop1 = next((lp for lp in f1.loops if lp.edge == edge), None)
                    loop2 = next((lp for lp in f2.loops if lp.edge == edge), None)
                    if loop1 and loop2:
                        uv1_a = loop1[uv_layer].uv
                        uv1_b = loop1.link_loop_next[uv_layer].uv
                        uv2_a = loop2[uv_layer].uv
                        uv2_b = loop2.link_loop_next[uv_layer].uv
                        # If UV coordinates on the same 3D edge don't match, it's a UV seam
                        if (uv1_a - uv2_b).length > 1e-4 or (uv1_b - uv2_a).length > 1e-4:
                            pinned_vert_indices.add(edge.verts[0].index)
                            pinned_vert_indices.add(edge.verts[1].index)

        return pinned_vert_indices

    @staticmethod
    def apply_planar_limited_dissolve(bm: Any, angle_limit_rad: float):
        if not bmesh or not bm or angle_limit_rad < 1e-4:
            return
        bmesh.ops.dissolve_limit(
            bm,
            angle_limit=angle_limit_rad,
            use_dissolve_boundaries=False,
            delimit={"SEAM", "SHARP", "MATERIAL"},
            edges=bm.edges[:],
            verts=bm.verts[:],
        )

    @staticmethod
    def inject_curvature_weights(
        obj: Any, bm: Any, pinned_vert_indices: set[int], group_name: str = "OmniMesh_Protection"
    ):
        if not bpy or not bmesh or not obj:
            return

        vg = obj.vertex_groups.get(group_name)
        if not vg:
            vg = obj.vertex_groups.new(name=group_name)

        dvert_lay = bm.verts.layers.deform.verify()

        for vert in bm.verts:
            max_dihedral = 0.0
            for edge in vert.link_edges:
                if len(edge.link_faces) == 2:
                    n1 = edge.link_faces[0].normal
                    n2 = edge.link_faces[1].normal
                    angle = n1.angle(n2, 0.0)
                    if angle > max_dihedral:
                        max_dihedral = angle

            # Normalized curvature weight [0.0, 1.0]
            w_curv = min(1.0, max_dihedral / math.pi)

            # Extra protection for pinned boundaries / seams
            w_boundary = 1.0 if vert.index in pinned_vert_indices else 0.0

            final_weight = min(1.0, 0.7 * w_curv + 0.3 * w_boundary)

            dvert = vert[dvert_lay]
            dvert[vg.index] = final_weight

    @staticmethod
    def execute_decimate_qem(
        obj: Any, target_ratio: float, use_curvature_weight: bool = True, group_name: str = "OmniMesh_Protection"
    ):
        if not bpy or not obj:
            return

        clamped_ratio = max(0.001, min(1.0, target_ratio))
        if clamped_ratio >= 0.999:
            return

        dec_mod = obj.modifiers.new(name="OmniMesh_Decimate", type="DECIMATE")
        dec_mod.decimate_type = "COLLAPSE"
        dec_mod.ratio = clamped_ratio
        dec_mod.use_symmetry = False
        dec_mod.use_collapse_triangulate = True

        if use_curvature_weight and group_name in obj.vertex_groups:
            dec_mod.vertex_group = group_name
            dec_mod.invert_vertex_group = True
            dec_mod.vertex_group_factor = 0.5

        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=dec_mod.name)

        # Cleanup protection vertex group
        vg = obj.vertex_groups.get(group_name)
        if vg:
            obj.vertex_groups.remove(vg)

    @staticmethod
    def prepare_and_clean_shape_keys(obj: Any, purge: bool = False):
        if not bpy or not obj or not obj.data.shape_keys:
            return

        # 1. Reset all shape keys to 0.0 (Basis)
        key_blocks = obj.data.shape_keys.key_blocks
        for kb in key_blocks:
            kb.value = 0.0

        # 2. If purge requested (LOD >= 2), remove all shape keys to save memory
        if purge:
            bpy.context.view_layer.objects.active = obj
            obj.shape_key_clear()
            for _ in range(len(key_blocks)):
                bpy.ops.object.shape_key_remove(all=True)
