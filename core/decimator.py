"""
Decimation and Simplification Engine for OmniMesh.
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

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
        """
        Identifies and tags all vertices belonging to:
        1. Open geometric boundaries (is_boundary or wire/loose edges)
        2. Non-manifold edge junctions (> 2 linked faces)
        3. Marked sharp edges and seam edges
        4. Material slot boundary edges
        5. UV seams across active/all UV layers (winding-order independent)
        """
        pinned_vert_indices: set[int] = set()
        if not bmesh or not bm:
            return pinned_vert_indices

        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.verts.index_update()

        # 1. Tag Boundaries & Non-Manifold Junctions
        for edge in bm.edges:
            if not edge.is_valid:
                continue
            num_faces = len(edge.link_faces)
            if edge.is_boundary or num_faces != 2:
                for v in edge.verts:
                    pinned_vert_indices.add(v.index)

        # 2. Tag Sharp Marks & Seam Edges
        for edge in bm.edges:
            if not edge.is_valid:
                continue
            if edge.seam or not edge.smooth:
                for v in edge.verts:
                    pinned_vert_indices.add(v.index)

        # 3. Tag Material Boundaries
        for edge in bm.edges:
            if not edge.is_valid or len(edge.link_faces) != 2:
                continue
            if edge.link_faces[0].material_index != edge.link_faces[1].material_index:
                for v in edge.verts:
                    pinned_vert_indices.add(v.index)

        # 4. Tag UV Seams across Face Loops (Winding-Order Invariant)
        uv_layers = list(bm.loops.layers.uv.values())
        if uv_layers:
            for edge in bm.edges:
                if not edge.is_valid or len(edge.link_faces) != 2:
                    continue
                f1, f2 = edge.link_faces[0], edge.link_faces[1]
                v0, v1 = edge.verts[0], edge.verts[1]

                for uv_layer in uv_layers:
                    # Find loop corresponding to v0 and v1 in f1
                    lp1_v0 = next((lp for lp in f1.loops if lp.vert == v0), None)
                    lp1_v1 = next((lp for lp in f1.loops if lp.vert == v1), None)
                    # Find loop corresponding to v0 and v1 in f2
                    lp2_v0 = next((lp for lp in f2.loops if lp.vert == v0), None)
                    lp2_v1 = next((lp for lp in f2.loops if lp.vert == v1), None)

                    if lp1_v0 and lp2_v0 and (lp1_v0[uv_layer].uv - lp2_v0[uv_layer].uv).length > 1e-4:
                        pinned_vert_indices.add(v0.index)
                        pinned_vert_indices.add(v1.index)
                        break

                    if lp1_v1 and lp2_v1 and (lp1_v1[uv_layer].uv - lp2_v1[uv_layer].uv).length > 1e-4:
                        pinned_vert_indices.add(v0.index)
                        pinned_vert_indices.add(v1.index)
                        break

        return pinned_vert_indices

    @staticmethod
    def apply_planar_limited_dissolve(bm: Any, angle_limit_rad: float):
        """
        Executes coplanar face decimation up to angle_limit_rad, preserving seams, sharp marks,
        and material boundaries.
        """
        if not bmesh or not bm or angle_limit_rad < 1e-4:
            return
        if len(bm.faces) <= 1 or len(bm.edges) == 0:
            return

        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        bmesh.ops.dissolve_limit(
            bm,
            angle_limit=min(math.radians(89.0), max(1e-4, angle_limit_rad)),
            use_dissolve_boundaries=False,
            delimit={"SEAM", "SHARP", "MATERIAL"},
            edges=bm.edges[:],
            verts=bm.verts[:],
        )

        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.verts.index_update()

    @staticmethod
    def inject_curvature_weights(
        obj: Any, bm: Any, pinned_vert_indices: set[int], group_name: str = "OmniMesh_Protection"
    ):
        """
        Computes maximum dihedral angle across link edges for each vertex and writes weights
        to the deform layer (vertex group). Tagged pinned vertices receive a weight of 1.0.
        """
        if not bpy or not bmesh or not obj:
            return

        vg = obj.vertex_groups.get(group_name)
        if not vg:
            vg = obj.vertex_groups.new(name=group_name)

        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.verts.index_update()
        bm.faces.index_update()
        bm.edges.index_update()
        dvert_lay = bm.verts.layers.deform.verify()
        vg_idx = vg.index
        num_verts = len(bm.verts)

        # High-speed vectorized path for dense geometry (NumPy scatter-max)
        if num_verts > 2000:
            try:
                import numpy as np

                num_faces = len(bm.faces)
                face_normals = np.array([f.normal for f in bm.faces], dtype=np.float32)

                # Collect manifold edge face and vertex indices
                manifold_edges = [e for e in bm.edges if len(e.link_faces) == 2]
                if manifold_edges and num_faces > 0:
                    f1_idx = np.fromiter(
                        (e.link_faces[0].index for e in manifold_edges), dtype=np.int32, count=len(manifold_edges)
                    )
                    f2_idx = np.fromiter(
                        (e.link_faces[1].index for e in manifold_edges), dtype=np.int32, count=len(manifold_edges)
                    )
                    v0_idx = np.fromiter(
                        (e.verts[0].index for e in manifold_edges), dtype=np.int32, count=len(manifold_edges)
                    )
                    v1_idx = np.fromiter(
                        (e.verts[1].index for e in manifold_edges), dtype=np.int32, count=len(manifold_edges)
                    )

                    # Vectorized dihedral angle computation
                    dots = np.clip(np.sum(face_normals[f1_idx] * face_normals[f2_idx], axis=1), -1.0, 1.0)
                    dihedral_angles = np.arccos(dots)

                    vert_max_angles = np.zeros(num_verts, dtype=np.float32)
                    np.maximum.at(vert_max_angles, v0_idx, dihedral_angles)
                    np.maximum.at(vert_max_angles, v1_idx, dihedral_angles)

                    weights = np.clip(vert_max_angles / np.float32(math.pi), 0.0, 1.0)
                    if pinned_vert_indices:
                        pinned_arr = np.fromiter(pinned_vert_indices, dtype=np.int32, count=len(pinned_vert_indices))
                        valid_pinned = pinned_arr[pinned_arr < num_verts]
                        weights[valid_pinned] = 1.0

                    for vert in bm.verts:
                        vert[dvert_lay][vg_idx] = float(weights[vert.index])
                    return
            except Exception as exc:
                logger.debug("Vectorized curvature fallback to BMesh: %s", exc)

        # Robust scalar fallback for small meshes or environments without NumPy
        for vert in bm.verts:
            max_dihedral = 0.0
            for edge in vert.link_edges:
                if len(edge.link_faces) == 2:
                    n1 = edge.link_faces[0].normal
                    n2 = edge.link_faces[1].normal
                    angle = n1.angle(n2, 0.0)
                    if angle > max_dihedral:
                        max_dihedral = angle

            # Strict protection for pinned boundaries / seams / non-manifold vertices
            if vert.index in pinned_vert_indices:
                final_weight = 1.0
            else:
                final_weight = min(1.0, max(0.0, max_dihedral / math.pi))

            dvert = vert[dvert_lay]
            dvert[vg_idx] = final_weight

    @staticmethod
    def execute_decimate_qem(
        obj: Any, target_ratio: float, use_curvature_weight: bool = True, group_name: str = "OmniMesh_Protection"
    ):
        """
        Applies quadric error metric (QEM) edge collapse decimation to the target mesh object.
        Cleans up temporary protection vertex groups upon completion.
        """
        if not bpy or not obj or getattr(obj, "type", "") != "MESH":
            return

        clamped_ratio = max(0.001, min(1.0, target_ratio))
        if clamped_ratio >= 0.999:
            # Clean up protection vertex group if returning without decimation
            vg = obj.vertex_groups.get(group_name)
            if vg:
                obj.vertex_groups.remove(vg)
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

        try:
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=dec_mod.name)
        except Exception:
            if dec_mod.name in obj.modifiers:
                obj.modifiers.remove(dec_mod)
        finally:
            # Cleanup protection vertex group
            vg = obj.vertex_groups.get(group_name)
            if vg:
                obj.vertex_groups.remove(vg)

    @staticmethod
    def prepare_and_clean_shape_keys(obj: Any, purge: bool = False):
        """
        Prepares shape keys by resetting evaluation values to 0.0 (Basis),
        and purges all shape keys if purge is True (for LOD >= 2).
        """
        if not bpy or not obj or not hasattr(obj, "data") or not obj.data or not obj.data.shape_keys:
            return

        # 1. Reset all shape keys to 0.0 (Basis)
        key_blocks = obj.data.shape_keys.key_blocks
        for kb in key_blocks:
            kb.value = 0.0

        # 2. If purge requested (LOD >= 2), remove all shape keys cleanly
        if purge:
            try:
                bpy.context.view_layer.objects.active = obj
                if hasattr(obj, "shape_key_clear"):
                    obj.shape_key_clear()
                bpy.ops.object.shape_key_remove(all=True)
            except (RuntimeError, AttributeError, TypeError) as exc:
                logger.debug("Shape key purge bypassed: %s", exc)
