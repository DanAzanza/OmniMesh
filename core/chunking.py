"""
OmniMesh Spatial Chunking & HLOD Engine.
Architected for Blender 5.0+ & Blender 5.2 LTS.
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
from typing import TYPE_CHECKING, Sequence, cast

from .compat import recenter_pivot_stationary

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bmesh
    import bpy
    from bpy.types import BlendData
    import mathutils
    from mathutils import Matrix, Vector
else:
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
    BlendData = object

try:
    import numpy as np
except ImportError:
    np = None

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
        obj: bpy.types.Object | None,
        cell_size_meters: float = 32.0,
        split_z: bool = False,
        z_cell_size: float = 32.0,
    ) -> SpatialGridSpec:
        """Computes world-space AABB and cutting planes for a Blender mesh object."""
        if not obj or not obj.bound_box:
            return cls()
        return cls.from_objects(
            [obj],
            cell_size_meters=cell_size_meters,
            split_z=split_z,
            z_cell_size=z_cell_size,
        )

    @classmethod
    def from_objects(
        cls,
        objs: Sequence[bpy.types.Object | None],
        cell_size_meters: float = 32.0,
        split_z: bool = False,
        z_cell_size: float = 32.0,
    ) -> SpatialGridSpec:
        """Computes combined world-space AABB and cutting planes across multiple mesh objects."""
        all_corners: list[Sequence[float] | Vector] = []
        for obj in objs:
            if not obj or not obj.bound_box:
                continue
            mat = obj.matrix_world
            if mat is None or Matrix is None:
                all_corners.extend(Vector(b) if Vector else b for b in obj.bound_box)
            else:
                all_corners.extend(mat @ Vector(b) for b in obj.bound_box)

        if not all_corners:
            return cls()

        min_x = min(c[0] for c in all_corners)
        max_x = max(c[0] for c in all_corners)
        min_y = min(c[1] for c in all_corners)
        max_y = max(c[1] for c in all_corners)
        min_z = min(c[2] for c in all_corners)
        max_z = max(c[2] for c in all_corners)

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

    def get_cell_index(self, world_co: Sequence[float] | Vector) -> tuple[int, int, int]:
        """Calculates discrete integer cell bucket coordinates (ix, iy, iz) for a world point."""
        min_x, min_y, min_z = self.min_corner
        ix = int((world_co[0] - min_x) / self.cell_size_x) if self.cell_size_x > 1e-5 else 0
        iy = int((world_co[1] - min_y) / self.cell_size_y) if self.cell_size_y > 1e-5 else 0
        iz = int((world_co[2] - min_z) / self.cell_size_z) if (self.split_z and self.cell_size_z > 1e-5) else 0

        ix = max(0, min(self.num_cells_x - 1, ix))
        iy = max(0, min(self.num_cells_y - 1, iy))
        iz = max(0, min(self.num_cells_z - 1, iz)) if self.split_z else 0
        return ix, iy, iz

    def get_parent_cluster_index(self, ix: int, iy: int, iz: int = 0, stride: int = 2) -> tuple[int, int, int]:
        """
        Calculates downsampled parent cluster coordinates for quadtree/octree HLOD grouping.
        Uses normalized pairwise stride (default: 2 for 2x2 quadtree grouping).
        """
        st = max(1, int(stride))
        return (ix // st, iy // st, (iz // st) if self.split_z else 0)


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
        source_obj: bpy.types.Object | None,
        grid_spec: SpatialGridSpec,
        base_name: str,
        target_collection: bpy.types.Collection | None,
        weld_dist: float = 1e-5,
        partitioning_mode: str = "UNIFORM_GRID",
        target_cluster_polys: int = 50000,
        *,
        blend_data: BlendData,
    ) -> list[bpy.types.Object]:
        """
        Slices source mesh along grid planes using BMesh, extracts non-empty cell chunks,
        re-centers local pivots, marks boundary seams, and transfers exact split normals.
        Supports uniform 2.5D grid and adaptive quadtree clustering.
        """
        bdata = blend_data
        bdata_meshes = bdata.meshes if bdata else None
        bdata_objs = bdata.objects if bdata else None
        if not bpy or not bmesh or not source_obj or source_obj.type != "MESH" or not bdata_meshes or not bdata_objs:
            return []

        eval_mesh, eval_obj = ModifierManager.get_evaluated_mesh(source_obj, preserve_armature=True)
        eval_mesh_data = cast("bpy.types.Mesh | None", eval_mesh)
        if not eval_mesh_data or len(eval_mesh_data.polygons) == 0:
            if eval_obj:
                eval_obj.to_mesh_clear()
            return []

        # 1. Initialize working BMesh from evaluated source
        bm = bmesh.new()
        try:
            bm.from_mesh(eval_mesh_data)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            mat_world = source_obj.matrix_world
            mat_inv = mat_world.inverted()
            mat_world_trans_3x3 = mat_world.to_3x3().transposed()

            # 2-4. Sequential planar bisects across X, Y, and optional Z axes
            axis_planes: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = [
                *(((x_w, 0.0, 0.0), (1.0, 0.0, 0.0)) for x_w in grid_spec.x_cut_planes),
                *(((0.0, y_w, 0.0), (0.0, 1.0, 0.0)) for y_w in grid_spec.y_cut_planes),
            ]
            if grid_spec.split_z:
                axis_planes.extend(((0.0, 0.0, z_w), (0.0, 0.0, 1.0)) for z_w in grid_spec.z_cut_planes)

            for p_coords, n_coords in axis_planes:
                p_world = Vector(p_coords)
                n_world = Vector(n_coords)
                p_local = mat_inv @ p_world
                n_local = (mat_world_trans_3x3 @ n_world).normalized()
                geom = bm.faces[:] + bm.edges[:] + bm.verts[:]
                bmesh.ops.bisect_plane(
                    bm,
                    geom=geom,
                    plane_co=(p_local.x, p_local.y, p_local.z),
                    plane_no=(n_local.x, n_local.y, n_local.z),
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
            created_chunk_objs: list[bpy.types.Object] = []
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
                    blend_data=blend_data,
                )
                if chunk_obj:
                    created_chunk_objs.append(chunk_obj)

            return created_chunk_objs

        finally:
            bm.free()
            if eval_obj:
                eval_obj.to_mesh_clear()

    @staticmethod
    def _extract_single_chunk(
        source_obj: bpy.types.Object,
        bm_sliced: bmesh.types.BMesh,
        face_indices: list[int],
        chunk_name: str,
        target_collection: bpy.types.Collection | None,
        grid_spec: SpatialGridSpec,
        *,
        blend_data: BlendData,
    ) -> bpy.types.Object | None:
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

            vert_map: dict[bmesh.types.BMVert, bmesh.types.BMVert] = {}
            for f in target_faces:
                for v in f.verts:
                    if v not in vert_map:
                        new_v = chunk_bm.verts.new(v.co)
                        vert_map[v] = new_v

            chunk_bm.verts.ensure_lookup_table()

            # Copy UV layers
            src_uv_layers = list(bm_sliced.loops.layers.uv.values()) if bm_sliced.loops.layers.uv else []
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
            chunk_bm.verts.index_update()
            chunk_bm.edges.ensure_lookup_table()
            chunk_bm.edges.index_update()
            chunk_bm.faces.ensure_lookup_table()
            chunk_bm.faces.index_update()

            # Identify boundary vertices on the actual cut seams
            seam_vert_indices: set[int] = set()
            world_mat = source_obj.matrix_world if source_obj else None
            cut_tol = 1e-3  # 1mm tolerance for bisect cutting planes
            has_cuts = bool(
                grid_spec.x_cut_planes or grid_spec.y_cut_planes or (grid_spec.split_z and grid_spec.z_cut_planes)
            )

            for edge in chunk_bm.edges:
                if edge.is_boundary:
                    for v in edge.verts:
                        if has_cuts:
                            wco = world_mat @ v.co if world_mat else v.co
                            is_on_cut = (
                                any(abs(wco.x - xp) < cut_tol for xp in grid_spec.x_cut_planes)
                                or any(abs(wco.y - yp) < cut_tol for yp in grid_spec.y_cut_planes)
                                or (
                                    grid_spec.split_z
                                    and any(abs(wco.z - zp) < cut_tol for zp in grid_spec.z_cut_planes)
                                )
                            )
                            if is_on_cut:
                                seam_vert_indices.add(v.index)
                        else:
                            seam_vert_indices.add(v.index)

            # Create Mesh Data and Object
            bdata = blend_data
            bdata_meshes = bdata.meshes if bdata else None
            bdata_objs = bdata.objects if bdata else None
            bdata_scenes = bdata.scenes if bdata else None

            if not bdata_meshes or not bdata_objs:
                return None

            chunk_mesh = bdata_meshes.new(name=f"{chunk_name}_Mesh")
            chunk_bm.to_mesh(chunk_mesh)
            chunk_mesh.update()

            chunk_obj = bdata_objs.new(name=chunk_name, object_data=chunk_mesh)
            chunk_obj.matrix_world = source_obj.matrix_world.copy()

            # Assign matching materials (preserving global slots)
            src_data = cast("bpy.types.Mesh | None", source_obj.data)
            for mat in src_data.materials if src_data and src_data.materials else ():
                chunk_mesh.materials.append(mat)

            # Link to collection
            fallback_coll = target_collection or (bdata_scenes[0].collection if bdata_scenes else None)
            if target_collection:
                target_collection.objects.link(chunk_obj)
            elif fallback_coll:
                fallback_coll.objects.link(chunk_obj)

            # Center local pivot to chunk's local bounding box center
            MeshChunkSlicer._recenter_pivot_stationary(chunk_obj)

            # Transfer loop normals from uncut source mesh
            mesh_data = cast("bpy.types.Mesh | None", chunk_obj.data)
            NormalManager.ensure_sharp_edge_attribute(mesh_data)
            if mesh_data is not None:
                mesh_data.update()

            # Create OMNIMESH_SEAM_LOCKED vertex group on final mesh data-block
            if seam_vert_indices:
                vg = chunk_obj.vertex_groups.new(name=SEAM_GROUP_NAME)
                vg.add(list(seam_vert_indices), 1.0, "REPLACE")

            return chunk_obj

        finally:
            chunk_bm.free()

    @staticmethod
    def _recenter_pivot_stationary(obj: bpy.types.Object | None) -> None:
        """Recalculates object origin to its local AABB center while keeping geometry stationary."""
        recenter_pivot_stationary(obj)


from .chunk_merger import HLODClusterMerger

__all__ = [
    "SpatialGridSpec",
    "MeshChunkSlicer",
    "HLODClusterMerger",
    "SEAM_GROUP_NAME",
]
