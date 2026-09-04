"""
OmniMesh Spatial Chunking & HLOD Generation Operators.
Architected for Blender 4.2+ LTS & Blender 5.2 LTS.
Features:
- LOD_OT_spatial_chunk_and_generate: Executes 2.5D AABB slicing, seam-locked LOD1 generation,
  and seam-welded unified HLOD merging for LOD2+.
- LOD_OT_voxel_scan_cleanup: Opt-in surface reconstruction pass for raw photogrammetry scans.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bmesh
    import bpy
    from bpy.types import Operator
except ImportError:
    bpy = None
    bmesh = None
    Operator = object

try:
    from core.chunking import HLODClusterMerger, MeshChunkSlicer, SpatialGridSpec
    from core.decimator import MeshDecimator
    from core.hierarchy import LayerCollectionGuard
    from core.materials import MaterialOptimizer
    from ui.utils import get_selected_mesh_objects, resolve_lod_context, safe_report
except (ImportError, ValueError):
    from ..core.chunking import HLODClusterMerger, MeshChunkSlicer, SpatialGridSpec
    from ..core.decimator import MeshDecimator
    from ..core.hierarchy import LayerCollectionGuard
    from ..core.materials import MaterialOptimizer
    from .utils import get_selected_mesh_objects, resolve_lod_context, safe_report


class LOD_OT_spatial_chunk_and_generate(Operator):
    """Spatially partitions massive assets into AABB grid chunks with seam-locked LODs and HLOD merging."""

    bl_idname = "lod_tool.spatial_chunk_and_generate"
    bl_label = "Partition & Generate Chunked LODs"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and get_selected_mesh_objects(context))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}

        props, target_obj, is_deriv = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            safe_report(self, {"WARNING"}, "No mesh objects selected for spatial partitioning.")
            return {"CANCELLED"}

        source_obj = context.active_object if context.active_object in mesh_objs else mesh_objs[0]
        base_name = props.export_base_name or source_obj.name
        base_name = base_name.split("_LOD")[0].split("_Chunk")[0]

        # 1. Compute Spatial Grid Specification
        cell_size = float(props.chunk_cell_size)
        split_z = bool(props.chunk_split_z)
        z_cell_size = float(props.chunk_cell_size_z)

        grid_spec = SpatialGridSpec.from_object(
            source_obj,
            cell_size_meters=cell_size,
            split_z=split_z,
            z_cell_size=z_cell_size,
        )

        total_cells = grid_spec.num_cells_x * grid_spec.num_cells_y * (grid_spec.num_cells_z if split_z else 1)
        logger.info(
            "Spatial Grid initialized: %dx%d (%d cells total, %.1fm x %.1fm)",
            grid_spec.num_cells_x,
            grid_spec.num_cells_y,
            total_cells,
            grid_spec.cell_size_x,
            grid_spec.cell_size_y,
        )

        # 2. Resolve or create LOD0 chunks collection
        lod0_coll_name = f"{base_name}_Chunks_LOD0"
        lod0_coll = bpy.data.collections.get(lod0_coll_name)
        if not lod0_coll:
            lod0_coll = bpy.data.collections.new(name=lod0_coll_name)
            context.scene.collection.children.link(lod0_coll)

        # 3. Perform Planar Slicing and Extract LOD0 Chunks
        try:
            part_mode = getattr(props, "chunk_partitioning_mode", "UNIFORM_GRID")
            target_polys = int(getattr(props, "adaptive_cluster_target_polys", 50000))
            chunk_objs_lod0 = MeshChunkSlicer.slice_and_partition(
                source_obj=source_obj,
                grid_spec=grid_spec,
                base_name=base_name,
                target_collection=lod0_coll,
                partitioning_mode=part_mode,
                target_cluster_polys=target_polys,
            )
        except Exception as exc:
            logger.error("Spatial slicing failed: %s", exc, exc_info=True)
            safe_report(self, {"ERROR"}, f"Spatial slicing failed: {exc}")
            return {"CANCELLED"}

        if not chunk_objs_lod0:
            safe_report(self, {"ERROR"}, "No chunks generated from mesh.")
            return {"CANCELLED"}

        # 4. Generate LOD1 with Seam Protection
        lod1_coll_name = f"{base_name}_Chunks_LOD1"
        lod1_coll = bpy.data.collections.get(lod1_coll_name)
        if not lod1_coll:
            lod1_coll = bpy.data.collections.new(name=lod1_coll_name)
            context.scene.collection.children.link(lod1_coll)

        chunk_objs_lod1: list[Any] = []
        with LayerCollectionGuard(context.view_layer, [lod0_coll, lod1_coll]):
            for chunk_lod0 in chunk_objs_lod0:
                # Duplicate chunk for LOD1
                c_data = chunk_lod0.data.copy()
                c_data.name = f"{chunk_lod0.name}_LOD1_Mesh"
                c_obj = bpy.data.objects.new(name=f"{chunk_lod0.name}_LOD1", object_data=c_data)
                c_obj.matrix_world = chunk_lod0.matrix_world.copy()
                lod1_coll.objects.link(c_obj)

                # Prune small surface materials
                try:
                    MaterialOptimizer.consolidate_micro_materials(c_obj, area_threshold_pct=0.5)
                except Exception as exc:
                    logger.debug("Material consolidation skipped for chunk %s: %s", c_obj.name, exc)

                # Decimate with strict boundary pinning
                MeshDecimator.execute_decimate_qem(
                    obj=c_obj,
                    target_ratio=0.5,
                    use_curvature_weight=True,
                    group_name="OMNIMESH_SEAM_LOCKED",
                    vertex_group_factor=1.0,
                    cleanup_group=False,
                )
                chunk_objs_lod1.append(c_obj)

        # 5. Generate HLOD (LOD2+) if enabled
        if props.enable_hlod and props.hlod_start_tier <= 2:
            hlod_coll_name = f"{base_name}_HLOD_LOD2"
            hlod_coll = bpy.data.collections.get(hlod_coll_name)
            if not hlod_coll:
                hlod_coll = bpy.data.collections.new(name=hlod_coll_name)
                context.scene.collection.children.link(hlod_coll)

            try:
                hlod_obj = HLODClusterMerger.merge_chunks_for_hlod(
                    chunk_objs=chunk_objs_lod1,
                    hlod_name=f"{base_name}_HLOD_LOD2",
                    target_collection=hlod_coll,
                    weld_dist=0.002,
                )
                if hlod_obj:
                    # Global aggressive decimation without seam boundary lock
                    MeshDecimator.execute_decimate_qem(
                        obj=hlod_obj,
                        target_ratio=0.15,
                        use_curvature_weight=False,
                        cleanup_group=True,
                    )
                    logger.info("Generated HLOD mesh: %s", hlod_obj.name)
            except Exception as exc:
                logger.error("HLOD cluster merging failed: %s", exc, exc_info=True)
                safe_report(self, {"WARNING"}, f"HLOD merging failed: {exc}")

        safe_report(
            self,
            {"INFO"},
            f"Successfully generated {len(chunk_objs_lod0)} chunks with seam protection and HLOD.",
        )
        return {"FINISHED"}


class LOD_OT_voxel_scan_cleanup(Operator):
    """Opt-in Pre-Processing: Remeshes raw, non-manifold photogrammetry scans into a clean watertight shell."""

    bl_idname = "lod_tool.voxel_scan_cleanup"
    bl_label = "Voxel Reconstruct Scan"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and context.active_object and getattr(context.active_object, "type", "") == "MESH")

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}

        obj = context.active_object
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        voxel_size = max(0.005, min(1.0, float(props.scan_remesh_voxel_size)))

        try:
            if hasattr(obj.data, "remesh_voxel_size"):
                obj.data.remesh_voxel_size = voxel_size
                obj.data.remesh_mode = "VOXEL"
                if hasattr(bpy.context, "temp_override"):
                    with bpy.context.temp_override(active_object=obj, object=obj, selected_objects=[obj]):
                        bpy.ops.object.voxel_remesh()
                elif hasattr(bpy.context, "view_layer") and hasattr(bpy.context.view_layer, "objects"):
                    bpy.context.view_layer.objects.active = obj
                    bpy.ops.object.voxel_remesh()

                safe_report(self, {"INFO"}, f"Voxel surface reconstruction applied (voxel={voxel_size:.3f}m).")
                return {"FINISHED"}
            else:
                safe_report(self, {"WARNING"}, "Voxel remeshing is not supported on this Blender version.")
                return {"CANCELLED"}
        except Exception as exc:
            logger.error("Voxel scan cleanup failed: %s", exc, exc_info=True)
            safe_report(self, {"ERROR"}, f"Voxel reconstruction failed: {exc}")
            return {"CANCELLED"}


CLASSES = (
    LOD_OT_spatial_chunk_and_generate,
    LOD_OT_voxel_scan_cleanup,
)


def register_chunk_operators() -> None:
    if not bpy:
        return
    for cls in CLASSES:
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:
            logger.debug("Safe unregister skipped %s: %s", getattr(cls, "__name__", "cls"), exc)
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            logger.debug("Failed registering %s: %s", getattr(cls, "__name__", "cls"), exc)


def unregister_chunk_operators() -> None:
    if not bpy:
        return
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:
            logger.debug("Safe unregister skipped %s: %s", getattr(cls, "__name__", "cls"), exc)
