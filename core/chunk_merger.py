"""
HLOD Cluster Merger for OmniMesh.

Merges chunk meshes into unified HLOD parent meshes with seam welding,
material slot unification, and bone-mapped skeletal vertex weight consolidation.
"""

from __future__ import annotations

import logging
from typing import Any

from .normals import NormalManager

try:
    import bmesh
    import bpy
    from mathutils import Matrix
except ImportError:
    bpy = None  # type: ignore
    bmesh = None  # type: ignore
    Matrix = None  # type: ignore

logger = logging.getLogger(__name__)


class HLODClusterMerger:
    """Merges chunk meshes into unified HLOD parent meshes with seam welding."""

    @staticmethod
    def merge_chunks_for_hlod(
        chunk_objs: list[Any],
        hlod_name: str,
        target_collection: Any,
        weld_dist: float = 0.002,
    ) -> Any:
        """
        Combines child chunk objects into a single unified mesh,
        welds seam vertices, consolidates materials, and preserves skeletal vertex groups.
        """
        if not bpy or not bmesh or not chunk_objs:
            return None

        valid_chunks = [
            c for c in chunk_objs if c and getattr(c, "type", "") == "MESH" and hasattr(c, "data") and c.data
        ]
        if not valid_chunks:
            return None

        # Build master material palette from all chunks to prevent slot aliasing
        master_materials: list[Any] = []
        for c in valid_chunks:
            for mat in getattr(c.data, "materials", []):
                if mat and mat not in master_materials:
                    master_materials.append(mat)

        # Build consolidated master vertex group list across all chunks
        master_vg_names: list[str] = []
        for c in valid_chunks:
            for vg in getattr(c, "vertex_groups", []):
                if vg.name not in master_vg_names:
                    master_vg_names.append(vg.name)

        merged_bm = bmesh.new()
        try:
            ref_mat_world = valid_chunks[0].matrix_world.copy()
            try:
                ref_mat_inv = ref_mat_world.inverted()
            except (ValueError, AttributeError, Exception):
                ref_mat_inv = Matrix.Identity(4) if Matrix is not None else ref_mat_world

            # Ensure merged BMesh has deform layer if any chunk is skinned
            merged_dvert = merged_bm.verts.layers.deform.verify() if master_vg_names else None

            for chunk_obj in valid_chunks:
                chunk_mesh = chunk_obj.data
                temp_bm = bmesh.new()
                try:
                    temp_bm.from_mesh(chunk_mesh)
                    # Transform chunk vertices to reference object local space
                    transform_to_ref = ref_mat_inv @ chunk_obj.matrix_world
                    temp_bm.transform(transform_to_ref)

                    # Re-map material slot indices to global master palette
                    chunk_mats = list(chunk_mesh.materials)
                    slot_map: dict[int, int] = {}
                    for old_idx, mat in enumerate(chunk_mats):
                        if mat in master_materials:
                            slot_map[old_idx] = master_materials.index(mat)
                        else:
                            slot_map[old_idx] = 0

                    for f in temp_bm.faces:
                        f.material_index = slot_map.get(f.material_index, 0)

                    # Append to merged BMesh
                    vert_map = {v: merged_bm.verts.new(v.co) for v in temp_bm.verts}
                    merged_bm.verts.ensure_lookup_table()

                    # Copy and remap skeletal deform weights by bone name
                    chunk_vg_names = [vg.name for vg in getattr(chunk_obj, "vertex_groups", [])]
                    temp_dvert = temp_bm.verts.layers.deform.active if hasattr(temp_bm.verts.layers, "deform") else None
                    if temp_dvert and merged_dvert and chunk_vg_names:
                        for v, new_v in vert_map.items():
                            if temp_dvert in v:
                                w_dict = v[temp_dvert]
                                for local_vg_idx, weight in w_dict.items():
                                    if 0 <= local_vg_idx < len(chunk_vg_names):
                                        bone_name = chunk_vg_names[local_vg_idx]
                                        if bone_name in master_vg_names:
                                            target_vg_idx = master_vg_names.index(bone_name)
                                            new_v[merged_dvert][target_vg_idx] = weight

                    # Copy UVs
                    temp_uv_layers = (
                        list(temp_bm.loops.layers.uv.values()) if hasattr(temp_bm.loops.layers, "uv") else []
                    )
                    for f in temp_bm.faces:
                        new_verts = [vert_map[v] for v in f.verts]
                        try:
                            new_f = merged_bm.faces.new(new_verts)
                            new_f.material_index = f.material_index
                            new_f.smooth = f.smooth

                            for temp_uv in temp_uv_layers:
                                merged_uv = merged_bm.loops.layers.uv.get(temp_uv.name)
                                if not merged_uv:
                                    merged_uv = merged_bm.loops.layers.uv.new(temp_uv.name)
                                for lp, new_lp in zip(f.loops, new_f.loops, strict=False):
                                    new_lp[merged_uv].uv = lp[temp_uv].uv
                        except (ValueError, IndexError):
                            continue

                finally:
                    temp_bm.free()

            merged_bm.verts.ensure_lookup_table()
            merged_bm.edges.ensure_lookup_table()
            merged_bm.faces.ensure_lookup_table()

            # Weld internal seam boundaries across joined chunks
            bmesh.ops.remove_doubles(merged_bm, verts=merged_bm.verts[:], dist=max(1e-5, weld_dist))

            # Create merged Blender mesh and object
            hlod_mesh = bpy.data.meshes.new(name=f"{hlod_name}_Mesh")
            merged_bm.to_mesh(hlod_mesh)
            hlod_mesh.update()

            hlod_obj = bpy.data.objects.new(name=hlod_name, object_data=hlod_mesh)
            hlod_obj.matrix_world = ref_mat_world

            # Allocate master vertex groups on hlod_obj
            for vg_name in master_vg_names:
                hlod_obj.vertex_groups.new(name=vg_name)

            # Populate master materials
            for mat in master_materials:
                hlod_mesh.materials.append(mat)

            # Link to target collection
            if target_collection and hasattr(target_collection, "objects"):
                target_collection.objects.link(hlod_obj)
            elif bpy.context.collection:
                bpy.context.collection.objects.link(hlod_obj)

            # Ensure auto-smooth / sharp attribute exists
            NormalManager.ensure_sharp_edge_attribute(hlod_mesh)
            hlod_mesh.update()

            return hlod_obj

        finally:
            merged_bm.free()
