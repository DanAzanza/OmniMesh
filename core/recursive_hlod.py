"""
Recursive Quadtree/Octree HLOD Manager for OmniMesh.
Spatially clusters adjacent chunk meshes into hierarchical LOD tiers (2x2 / 2x2x2)
with seam welding, stationary pivot recentering, and optional terminal voxel proxy shell.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from .chunk_merger import HLODClusterMerger
from .decimator import MeshDecimator

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


@dataclass
class HierarchicalClusterNode:
    """Represents a spatial cluster node in a recursive quadtree/octree hierarchy."""

    cluster_coords: tuple[int, int, int]
    level: int
    child_objects: list[Any]
    name: str = ""


class RecursiveHLODManager:
    """
    Orchestrates recursive pairwise / quadtree HLOD generation across distance tiers.
    """

    @staticmethod
    def extract_cell_coordinates(obj: Any, grid_spec: Any = None) -> tuple[int, int, int]:
        """
        Extracts (ix, iy, iz) discrete grid coordinates from object custom properties,
        object name patterns (e.g. Chunk_X1_Y2_Z0 or Cluster_X0-1_Y0-1), or bounding box centroid.
        """
        if not obj:
            return (0, 0, 0)

        # 1. Custom RNA property check
        if hasattr(obj, "get"):
            c_ix = obj.get("_chunk_ix")
            c_iy = obj.get("_chunk_iy")
            if isinstance(c_ix, (int, float)) and isinstance(c_iy, (int, float)):
                c_iz = obj.get("_chunk_iz", 0)
                iz_val = int(c_iz) if isinstance(c_iz, (int, float)) else 0
                return (int(c_ix), int(c_iy), iz_val)

        # 2. Regex matching on object name
        name = getattr(obj, "name", "")
        # Match Chunk_X{x}_Y{y}
        m = re.search(r"X(\d+)[-_]Y(\d+)(?:[-_]Z(\d+))?", name)
        if m:
            ix = int(m.group(1))
            iy = int(m.group(2))
            iz = int(m.group(3)) if m.group(3) else 0
            return (ix, iy, iz)

        # Match Cluster_X{min}-{max}_Y{min}-{max}
        m_clust = re.search(r"Cluster_X(\d+)-(\d+)_Y(\d+)-(\d+)(?:_Z(\d+))?", name)
        if m_clust:
            ix = int(m_clust.group(1))
            iy = int(m_clust.group(3))
            iz = int(m_clust.group(5)) if m_clust.group(5) else 0
            return (ix, iy, iz)

        # 3. Fallback: world-space bounding box center against grid_spec
        if grid_spec and hasattr(obj, "matrix_world") and hasattr(obj, "bound_box") and obj.bound_box:
            try:
                mat = obj.matrix_world
                corners = [mat @ Vector(b) for b in obj.bound_box] if Vector and mat else obj.bound_box
                cx = sum(c[0] for c in corners) / len(corners)
                cy = sum(c[1] for c in corners) / len(corners)
                cz = sum(c[2] for c in corners) / len(corners)
                return grid_spec.get_cell_index((cx, cy, cz))
            except Exception as exc:
                logger.debug("Bounding box coordinate resolution skipped: %s", exc)

        return (0, 0, 0)

    @classmethod
    def group_chunks_quadtree(
        cls,
        chunk_objs: list[Any],
        grid_spec: Any = None,
        stride: int = 2,
    ) -> dict[tuple[int, int, int], list[Any]]:
        """
        Groups chunk meshes into 2x2 (or 2x2x2) parent clusters using normalized stride-2 reduction.
        Handles non-power-of-two (odd) grid dimensions gracefully.
        """
        clusters: dict[tuple[int, int, int], list[Any]] = {}
        for obj in chunk_objs:
            if not obj or getattr(obj, "type", "") != "MESH":
                continue
            ix, iy, iz = cls.extract_cell_coordinates(obj, grid_spec)
            parent_coords = (ix // stride, iy // stride, (iz // stride) if getattr(grid_spec, "split_z", False) else 0)
            clusters.setdefault(parent_coords, []).append(obj)

        return clusters

    @classmethod
    def build_hierarchical_tier(
        cls,
        parent_clusters: dict[tuple[int, int, int], list[Any]],
        base_name: str,
        tier_index: int,
        target_collection: Any,
        target_ratio: float = 0.15,
        weld_dist: float = 0.002,
        is_terminal_tier: bool = False,
        use_voxel_shell: bool = False,
        voxel_size: float = 0.5,
        context: Any = None,
    ) -> list[Any]:
        """
        Merges chunk clusters for a specific HLOD tier, recents pivots stationary,
        decimates, and optionally seals into a voxel shell on terminal tier.
        """
        generated_hlod_objs: list[Any] = []

        for (cx, cy, cz), cluster_members in parent_clusters.items():
            if not cluster_members:
                continue

            cluster_suffix = f"X{cx}_Y{cy}"
            if cz > 0:
                cluster_suffix += f"_Z{cz}"

            hlod_name = f"{base_name}_HLOD_LOD{tier_index}_{cluster_suffix}"

            # If cluster contains only 1 chunk, perform lightweight pass-through decimation
            if len(cluster_members) == 1:
                source_chunk = cluster_members[0]
                if not hasattr(source_chunk, "data") or not source_chunk.data:
                    continue
                hlod_mesh = source_chunk.data.copy()
                hlod_mesh.name = f"{hlod_name}_Mesh"
                hlod_obj = bpy.data.objects.new(name=hlod_name, object_data=hlod_mesh) if bpy else None
                if hlod_obj:
                    hlod_obj.matrix_world = source_chunk.matrix_world.copy()
                    if target_collection and hasattr(target_collection, "objects"):
                        target_collection.objects.link(hlod_obj)
                    hlod_obj["_chunk_ix"] = cx
                    hlod_obj["_chunk_iy"] = cy
                    hlod_obj["_chunk_iz"] = cz

                    # Optional: Terminal Voxel Proxy Shell
                    if is_terminal_tier and use_voxel_shell:
                        cls.apply_voxel_proxy_shell(hlod_obj, voxel_size_m=voxel_size, context=context)

                    # Decimate
                    MeshDecimator.execute_decimate_qem(
                        obj=hlod_obj,
                        target_ratio=target_ratio,
                        use_curvature_weight=False,
                        group_name="" if is_terminal_tier else "OMNIMESH_SEAM_LOCKED",
                        cleanup_group=is_terminal_tier,
                    )
                    generated_hlod_objs.append(hlod_obj)
                continue

            # Multi-chunk cluster: Merge with seam welding
            hlod_obj = HLODClusterMerger.merge_chunks_for_hlod(
                chunk_objs=cluster_members,
                hlod_name=hlod_name,
                target_collection=target_collection,
                weld_dist=weld_dist,
            )

            if not hlod_obj:
                continue

            # Store downsampled cluster coordinates for subsequent recursive levels
            hlod_obj["_chunk_ix"] = cx
            hlod_obj["_chunk_iy"] = cy
            hlod_obj["_chunk_iz"] = cz

            # Optional: Terminal Voxel Proxy Shell
            if is_terminal_tier and use_voxel_shell:
                cls.apply_voxel_proxy_shell(hlod_obj, voxel_size_m=voxel_size, context=context)

            # Decimate merged cluster
            MeshDecimator.execute_decimate_qem(
                obj=hlod_obj,
                target_ratio=target_ratio,
                use_curvature_weight=False,
                group_name="" if is_terminal_tier else "OMNIMESH_SEAM_LOCKED",
                cleanup_group=is_terminal_tier,
            )
            generated_hlod_objs.append(hlod_obj)

        return generated_hlod_objs

    @classmethod
    def apply_voxel_proxy_shell(
        cls,
        obj: Any,
        voxel_size_m: float = 0.5,
        context: Any = None,
    ) -> bool:
        """
        Evaluates a watertight voxel remesh modifier via depsgraph (without UI bpy.ops context crash),
        clamps voxel size to prevent Out-Of-Memory freezes, and preserves auto-smooth normals.
        """
        if not bpy or not obj or getattr(obj, "type", "") != "MESH" or not hasattr(obj, "data"):
            return False

        mesh = obj.data
        if not hasattr(mesh, "vertices") or len(mesh.vertices) == 0:
            return False

        # Compute bounding dimensions to dynamically clamp minimum voxel size against OOM
        verts = mesh.vertices
        min_co = [min(v.co[i] for v in verts) for i in range(3)]
        max_co = [max(v.co[i] for v in verts) for i in range(3)]
        max_dim = max(max_co[i] - min_co[i] for i in range(3))

        # Clamp voxel size so grid count never exceeds 512 in any axis
        safe_min_voxel = max(0.01, max_dim / 512.0)
        clamped_voxel_size = max(safe_min_voxel, float(voxel_size_m))

        mod = obj.modifiers.new(name="OMNIMESH_HLOD_REMESH", type="REMESH")
        mod.mode = "VOXEL"
        mod.voxel_size = clamped_voxel_size
        mod.adaptivity = 0.0

        try:
            # Safe evaluation via depsgraph (headless-compatible, zero bpy.ops UI dependencies)
            eval_depsgraph = (
                context.evaluated_depsgraph_get()
                if context and hasattr(context, "evaluated_depsgraph_get")
                else (
                    bpy.context.evaluated_depsgraph_get()
                    if hasattr(bpy, "context") and hasattr(bpy.context, "evaluated_depsgraph_get")
                    else None
                )
            )
            if eval_depsgraph:
                eval_obj = obj.evaluated_get(eval_depsgraph)
                new_mesh = bpy.data.meshes.new_from_object(
                    eval_obj, preserve_all_data_layers=True, depsgraph=eval_depsgraph
                )
                obj.modifiers.remove(mod)

                old_mesh = obj.data
                obj.data = new_mesh
                try:
                    bpy.data.meshes.remove(old_mesh)
                except Exception as exc:
                    logger.debug("Could not remove old mesh: %s", exc)
                return True
            else:
                obj.modifiers.remove(mod)
                return False
        except Exception as exc:
            logger.warning("Voxel proxy remesh evaluation failed: %s", exc)
            try:
                if mod in obj.modifiers:
                    obj.modifiers.remove(mod)
            except (RuntimeError, AttributeError, ReferenceError) as mod_exc:
                logger.debug("Could not remove modifier during error cleanup: %s", mod_exc)
            return False
