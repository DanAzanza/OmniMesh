"""
OmniMesh Spatial Chunking & HLOD Engine.
Architected for Blender 4.2+ LTS & Blender 5.2 LTS.
Features:
- SpatialGridSpec: 2.5D AABB bounding envelope computation and cell indexing.
- MeshChunkSlicer: In-place BMesh planar bisecting, 4-way intersection cleaning,
  vectorized face binning, and chunk object extraction with local pivot recentering.
- SeamPinningEngine: Boundary vertex marking into 'OMNIMESH_SEAM_LOCKED'.
- HLODClusterMerger: Global material palette unification, seam welding, and global decimation prep.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("OmniMesh.Chunking")

try:
    import bmesh
    import bpy
    import mathutils
    from mathutils import Matrix, Vector
except ImportError:
    bpy = None
    bmesh = None
    mathutils = None
    Matrix = None
    Vector = None

try:
    import numpy as np
except ImportError:
    np = None

try:
    from core.modifiers import ModifierManager
    from core.normals import NormalManager
except (ImportError, ValueError):
    from .modifiers import ModifierManager
    from .normals import NormalManager


SEAM_GROUP_NAME = "OMNIMESH_SEAM_LOCKED"


@dataclass
class SpatialGridSpec:
    """Defines 2.5D AABB spatial partitioning bounds and slicing planes."""

    min_corner: tuple[float, float, float] = (0.0, 0.0, 0.0)
    max_corner: tuple[float, float, float] = (0.0, 0.0, 0.0)
    cell_size_x: float = 32.0
    cell_size_y: float = 32.0
    cell_size_z: float = 32.0
    split_z: bool = False
    num_cells_x: int = 1
    num_cells_y: int = 1
    num_cells_z: int = 1
    x_cut_planes: list[float] = field(default_factory=list)
    y_cut_planes: list[float] = field(default_factory=list)
    z_cut_planes: list[float] = field(default_factory=list)

    @classmethod
    def from_object(
        cls,
        obj: Any,
        cell_size_meters: float = 32.0,
        split_z: bool = False,
        z_cell_size: float = 32.0,
    ) -> SpatialGridSpec:
        """Computes world-space AABB and cutting planes for a Blender mesh object."""
        if not obj or not hasattr(obj, "bound_box") or not obj.bound_box:
            return cls()

        mat = getattr(obj, "matrix_world", None)
        if mat is None or Matrix is None:
            corners = [Vector(b) if Vector else b for b in obj.bound_box]
        else:
            corners = [mat @ Vector(b) for b in obj.bound_box]

        min_x = min(c[0] for c in corners)
        max_x = max(c[0] for c in corners)
        min_y = min(c[1] for c in corners)
        max_y = max(c[1] for c in corners)
        min_z = min(c[2] for c in corners)
        max_z = max(c[2] for c in corners)

        dx = max(1e-4, max_x - min_x)
        dy = max(1e-4, max_y - min_y)
        dz = max(1e-4, max_z - min_z)

        cs_x = max(1.0, float(cell_size_meters))
        cs_y = max(1.0, float(cell_size_meters))
        cs_z = max(1.0, float(z_cell_size))

        nx = max(1, math.ceil(dx / cs_x))
        ny = max(1, math.ceil(dy / cs_y))
        nz = max(1, math.ceil(dz / cs_z)) if split_z else 1

        step_x = dx / nx
        step_y = dy / ny
        step_z = dz / nz if split_z else dz

        x_planes = [min_x + k * step_x for k in range(1, nx)]
        y_planes = [min_y + k * step_y for k in range(1, ny)]
        z_planes = [min_z + k * step_z for k in range(1, nz)] if split_z else []

        return cls(
            min_corner=(min_x, min_y, min_z),
            max_corner=(max_x, max_y, max_z),
            cell_size_x=step_x,
            cell_size_y=step_y,
            cell_size_z=step_z,
            split_z=split_z,
            num_cells_x=nx,
            num_cells_y=ny,
            num_cells_z=nz,
            x_cut_planes=x_planes,
            y_cut_planes=y_planes,
            z_cut_planes=z_planes,
        )

    def get_cell_index(self, world_co: tuple[float, float, float] | Any) -> tuple[int, int, int]:
        """Calculates discrete integer cell bucket coordinates (ix, iy, iz) for a world point."""
        min_x, min_y, min_z = self.min_corner
        ix = int((world_co[0] - min_x) / self.cell_size_x) if self.cell_size_x > 1e-5 else 0
        iy = int((world_co[1] - min_y) / self.cell_size_y) if self.cell_size_y > 1e-5 else 0
        iz = int((world_co[2] - min_z) / self.cell_size_z) if (self.split_z and self.cell_size_z > 1e-5) else 0

        ix = max(0, min(self.num_cells_x - 1, ix))
        iy = max(0, min(self.num_cells_y - 1, iy))
        iz = max(0, min(self.num_cells_z - 1, iz)) if self.split_z else 0
        return ix, iy, iz


class AdaptiveCellClusterer:
    """Hierarchically clusters adjacent sparse grid cells to balance polycounts with zero T-junctions."""

    @staticmethod
    def cluster_cells(
        buckets: dict[tuple[int, int, int], list[int]],
        grid_spec: SpatialGridSpec,
        target_polys_per_cluster: int = 50000,
    ) -> dict[str, list[int]]:
        """
        Groups adjacent cell buckets into clusters if combined polygon count <= target_polys_per_cluster.
        Returns mapping of chunk_name_suffix -> list of face indices.
        """
        if not buckets:
            return {}

        clustered: dict[str, list[int]] = {}
        visited: set[tuple[int, int, int]] = set()

        nx = grid_spec.num_cells_x
        ny = grid_spec.num_cells_y
        nz = grid_spec.num_cells_z if grid_spec.split_z else 1

        # Attempt 2x2 quad grouping in X and Y
        for iz in range(nz):
            for ix in range(0, nx, 2):
                for iy in range(0, ny, 2):
                    quad_cells = [
                        (ix, iy, iz),
                        (ix + 1, iy, iz),
                        (ix, iy + 1, iz),
                        (ix + 1, iy + 1, iz),
                    ]
                    # Filter to valid in-bounds unvisited cells
                    valid_quad = [c for c in quad_cells if c[0] < nx and c[1] < ny and c not in visited]
                    if not valid_quad:
                        continue

                    # Sum total faces across this block
                    block_faces: list[int] = []
                    for c in valid_quad:
                        block_faces.extend(buckets.get(c, []))

                    # If within polygon budget and multiple cells exist, cluster together
                    if len(block_faces) > 0 and len(block_faces) <= target_polys_per_cluster and len(valid_quad) > 1:
                        min_x = min(c[0] for c in valid_quad)
                        max_x = max(c[0] for c in valid_quad)
                        min_y = min(c[1] for c in valid_quad)
                        max_y = max(c[1] for c in valid_quad)
                        cluster_name = f"Cluster_X{min_x}-{max_x}_Y{min_y}-{max_y}"
                        if grid_spec.split_z:
                            cluster_name += f"_Z{iz}"
                        clustered[cluster_name] = block_faces
                        for c in valid_quad:
                            visited.add(c)
                    else:
                        # Keep each cell individual
                        for c in valid_quad:
                            c_faces = buckets.get(c, [])
                            if c_faces:
                                c_name = f"Chunk_X{c[0]}_Y{c[1]}"
                                if grid_spec.split_z:
                                    c_name += f"_Z{c[2]}"
                                clustered[c_name] = c_faces
                            visited.add(c)

        # Any remaining unvisited cells
        for cell, faces in buckets.items():
            if cell not in visited and faces:
                c_name = f"Chunk_X{cell[0]}_Y{cell[1]}"
                if grid_spec.split_z:
                    c_name += f"_Z{cell[2]}"
                clustered[c_name] = faces
                visited.add(cell)

        return clustered


class MeshChunkSlicer:
    """Executes deterministic planar slicing and extracts isolated chunk objects."""

    @staticmethod
    def slice_and_partition(
        source_obj: Any,
        grid_spec: SpatialGridSpec,
        base_name: str,
        target_collection: Any,
        weld_dist: float = 1e-5,
        partitioning_mode: str = "UNIFORM_GRID",
        target_cluster_polys: int = 50000,
    ) -> list[Any]:
        """
        Slices source mesh along grid planes using BMesh, extracts non-empty cell chunks,
        re-centers local pivots, marks boundary seams, and transfers exact split normals.
        Supports uniform 2.5D grid and adaptive quadtree clustering.
        """
        if not bpy or not bmesh or not source_obj or getattr(source_obj, "type", "") != "MESH":
            return []

        eval_mesh, eval_obj = ModifierManager.get_evaluated_mesh(source_obj, preserve_armature=True)
        if not eval_mesh or len(getattr(eval_mesh, "polygons", [])) == 0:
            if eval_obj and hasattr(eval_obj, "to_mesh_clear"):
                eval_obj.to_mesh_clear()
            return []

        # 1. Initialize working BMesh from evaluated source
        bm = bmesh.new()
        try:
            bm.from_mesh(eval_mesh)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            mat_world = source_obj.matrix_world
            mat_inv = mat_world.inverted()
            mat_inv_trans = mat_inv.transposed().to_3x3()

            # 2. Sequential X-axis planar bisects
            for x_world in grid_spec.x_cut_planes:
                p_world = Vector((x_world, 0.0, 0.0))
                n_world = Vector((1.0, 0.0, 0.0))
                p_local = mat_inv @ p_world
                n_local = (mat_inv_trans @ n_world).normalized()

                geom = bm.faces[:] + bm.edges[:] + bm.verts[:]
                bmesh.ops.bisect_plane(
                    bm,
                    geom=geom,
                    plane_co=p_local,
                    plane_no=n_local,
                    dist=1e-5,
                    clear_inner=False,
                    clear_outer=False,
                )

            # 3. Sequential Y-axis planar bisects
            for y_world in grid_spec.y_cut_planes:
                p_world = Vector((0.0, y_world, 0.0))
                n_world = Vector((0.0, 1.0, 0.0))
                p_local = mat_inv @ p_world
                n_local = (mat_inv_trans @ n_world).normalized()

                geom = bm.faces[:] + bm.edges[:] + bm.verts[:]
                bmesh.ops.bisect_plane(
                    bm,
                    geom=geom,
                    plane_co=p_local,
                    plane_no=n_local,
                    dist=1e-5,
                    clear_inner=False,
                    clear_outer=False,
                )

            # 4. Optional Z-axis planar bisects
            if grid_spec.split_z:
                for z_world in grid_spec.z_cut_planes:
                    p_world = Vector((0.0, 0.0, z_world))
                    n_world = Vector((0.0, 0.0, 1.0))
                    p_local = mat_inv @ p_world
                    n_local = (mat_inv_trans @ n_world).normalized()

                    geom = bm.faces[:] + bm.edges[:] + bm.verts[:]
                    bmesh.ops.bisect_plane(
                        bm,
                        geom=geom,
                        plane_co=p_local,
                        plane_no=n_local,
                        dist=1e-5,
                        clear_inner=False,
                        clear_outer=False,
                    )

            # 5. Weld 4-way intersection vertices to eliminate micro-slivers
            bm.verts.ensure_lookup_table()
            bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=max(1e-6, weld_dist))

            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            bm.faces.index_update()

            # 6. Bin faces into cell buckets based on world-space face centroids
            buckets: dict[tuple[int, int, int], list[int]] = {}
            for face in bm.faces:
                center_local = face.calc_center_median()
                center_world = mat_world @ center_local
                cell_key = grid_spec.get_cell_index(center_world)
                if cell_key not in buckets:
                    buckets[cell_key] = []
                buckets[cell_key].append(face.index)

            # 7. Cluster or map to chunks
            if partitioning_mode == "ADAPTIVE_CLUSTERING":
                chunk_groups = AdaptiveCellClusterer.cluster_cells(
                    buckets=buckets,
                    grid_spec=grid_spec,
                    target_polys_per_cluster=target_cluster_polys,
                )
            else:
                chunk_groups = {}
                for (ix, iy, iz), face_indices in sorted(buckets.items()):
                    if not face_indices:
                        continue
                    c_suffix = f"Chunk_X{ix}_Y{iy}" if not grid_spec.split_z else f"Chunk_X{ix}_Y{iy}_Z{iz}"
                    chunk_groups[c_suffix] = face_indices

            # 8. Extract each non-empty group into a distinct Blender mesh object
            created_chunk_objs: list[Any] = []
            for chunk_suffix, face_indices in sorted(chunk_groups.items()):
                if not face_indices:
                    continue

                chunk_name = f"{base_name}_{chunk_suffix}"
                chunk_obj = MeshChunkSlicer._extract_single_chunk(
                    source_obj=source_obj,
                    bm_sliced=bm,
                    face_indices=face_indices,
                    chunk_name=chunk_name,
                    target_collection=target_collection,
                    grid_spec=grid_spec,
                )
                if chunk_obj:
                    created_chunk_objs.append(chunk_obj)

            return created_chunk_objs

        finally:
            bm.free()
            if eval_obj and hasattr(eval_obj, "to_mesh_clear"):
                eval_obj.to_mesh_clear()

    @staticmethod
    def _extract_single_chunk(
        source_obj: Any,
        bm_sliced: Any,
        face_indices: list[int],
        chunk_name: str,
        target_collection: Any,
        grid_spec: SpatialGridSpec,
    ) -> Any:
        """Extracts specified face indices from sliced BMesh into an independent mesh object."""
        if not bpy or not bmesh:
            return None

        # Build isolated BMesh for this chunk
        chunk_bm = bmesh.new()
        try:
            # Map original vertex indices to chunk vertices
            target_faces = [bm_sliced.faces[idx] for idx in face_indices if idx < len(bm_sliced.faces)]
            if not target_faces:
                return None

            vert_map: dict[Any, Any] = {}
            for f in target_faces:
                for v in f.verts:
                    if v not in vert_map:
                        new_v = chunk_bm.verts.new(v.co)
                        vert_map[v] = new_v

            chunk_bm.verts.ensure_lookup_table()

            # Copy UV layers
            src_uv_layers = list(bm_sliced.loops.layers.uv.values()) if hasattr(bm_sliced.loops.layers, "uv") else []
            chunk_uv_layers = []
            for src_uv in src_uv_layers:
                chunk_uv = chunk_bm.loops.layers.uv.new(src_uv.name)
                chunk_uv_layers.append((src_uv, chunk_uv))

            # Create faces and copy loop attributes
            for f in target_faces:
                new_verts = [vert_map[v] for v in f.verts]
                try:
                    new_f = chunk_bm.faces.new(new_verts)
                    new_f.material_index = f.material_index
                    new_f.smooth = f.smooth

                    for src_uv, chunk_uv in chunk_uv_layers:
                        for lp, new_lp in zip(f.loops, new_f.loops, strict=False):
                            new_lp[chunk_uv].uv = lp[src_uv].uv
                except (ValueError, IndexError):
                    continue

            chunk_bm.verts.ensure_lookup_table()
            chunk_bm.edges.ensure_lookup_table()
            chunk_bm.faces.ensure_lookup_table()

            # Identify boundary vertices on the cut seams
            seam_vert_indices: set[int] = set()
            for edge in chunk_bm.edges:
                if getattr(edge, "is_boundary", False):
                    for v in edge.verts:
                        seam_vert_indices.add(v.index)

            # Create Mesh Data and Object
            chunk_mesh = bpy.data.meshes.new(name=f"{chunk_name}_Mesh")
            chunk_bm.to_mesh(chunk_mesh)
            chunk_mesh.update()

            chunk_obj = bpy.data.objects.new(name=chunk_name, object_data=chunk_mesh)
            chunk_obj.matrix_world = source_obj.matrix_world.copy()

            # Assign matching materials (preserving global slots)
            for mat in source_obj.data.materials:
                chunk_mesh.materials.append(mat)

            # Link to collection
            if target_collection and hasattr(target_collection, "objects"):
                target_collection.objects.link(chunk_obj)
            elif bpy.context.collection:
                bpy.context.collection.objects.link(chunk_obj)

            # Create OMNIMESH_SEAM_LOCKED vertex group
            if seam_vert_indices:
                vg = chunk_obj.vertex_groups.new(name=SEAM_GROUP_NAME)
                vg.add(list(seam_vert_indices), 1.0, "REPLACE")

            # Center local pivot to chunk's local bounding box center
            MeshChunkSlicer._recenter_pivot_stationary(chunk_obj)

            # Transfer loop normals from uncut source mesh
            NormalManager.reproject_custom_split_normals(chunk_obj, source_obj)
            NormalManager.ensure_sharp_edge_attribute(chunk_mesh)
            chunk_mesh.update()

            return chunk_obj

        finally:
            chunk_bm.free()

    @staticmethod
    def _recenter_pivot_stationary(obj: Any) -> None:
        """
        Recalculates object origin to its local bounding box center
        while compensating vertex coordinates so world geometry remains stationary.
        """
        if not obj or getattr(obj, "type", "") != "MESH" or not hasattr(obj, "data") or not obj.data:
            return
        mesh = obj.data
        if not hasattr(mesh, "vertices") or len(mesh.vertices) == 0:
            return

        verts = mesh.vertices
        min_co = [min(v.co[i] for v in verts) for i in range(3)]
        max_co = [max(v.co[i] for v in verts) for i in range(3)]
        center_coords = [(min_co[i] + max_co[i]) * 0.5 for i in range(3)]
        center_len = math.sqrt(sum(c * c for c in center_coords))

        if center_len < 1e-5:
            return

        center_offset = Vector(center_coords) if Vector is not None else center_coords

        # Shift all vertices by -center_offset
        for v in verts:
            try:
                v.co -= center_offset
            except (TypeError, AttributeError):
                v.co = type(v.co)([v.co[i] - center_coords[i] for i in range(3)])

        # Compensate object world transform by +center_local
        if hasattr(obj, "matrix_world") and obj.matrix_world is not None and Matrix is not None:
            trans_mat = Matrix.Translation(Vector(center_coords) if Vector else center_coords)
            obj.matrix_world = obj.matrix_world @ trans_mat


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
        welds seam vertices, and clears seam protection vertex groups for global decimation.
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

        merged_bm = bmesh.new()
        try:
            ref_mat_world = valid_chunks[0].matrix_world.copy()
            ref_mat_inv = ref_mat_world.inverted()

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
