# pyright: reportInvalidTypeForm=none
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
from typing import TYPE_CHECKING, Any, cast

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bmesh
    import bpy
    from bpy.types import Operator
else:
    try:
        import bmesh
        import bpy
        from bpy.types import Operator
    except ImportError:
        bpy = None
        bmesh = None
        Operator = object

try:
    from ..core.chunking import HLODClusterMerger, MeshChunkSlicer, SpatialGridSpec
    from ..core.decimator import MeshDecimator
    from ..core.hierarchy import LayerCollectionGuard
    from ..core.materials import MaterialOptimizer
    from ..core.recursive_hlod import RecursiveHLODManager
    from .utils import get_selected_mesh_objects, resolve_lod_context, safe_report
except (ImportError, ValueError):
    from core.chunking import HLODClusterMerger, MeshChunkSlicer, SpatialGridSpec
    from core.decimator import MeshDecimator
    from core.hierarchy import LayerCollectionGuard
    from core.materials import MaterialOptimizer
    from core.recursive_hlod import RecursiveHLODManager
    from ui.utils import get_selected_mesh_objects, resolve_lod_context, safe_report


class LOD_OT_spatial_chunk_and_generate(Operator):
    """Spatially partitions massive assets into AABB grid chunks with seam-locked LODs and HLOD merging."""

    bl_idname = "lod_tool.spatial_chunk_and_generate"
    bl_label = "Partition & Generate Chunked LODs"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and get_selected_mesh_objects(context))

    @staticmethod
    def _resolve_decimation_ratios(props: Any) -> tuple[float, float]:
        lod1_ratio = 0.5
        hlod_ratio = 0.15
        if len(props.lods) >= 2:
            lod1_ratio = max(0.01, min(0.99, props.lods[1].target_tris_pct / 100.0))
            hlod_idx = min(len(props.lods) - 1, max(2, int(props.hlod_start_tier)))
            hlod_ratio = max(0.005, min(0.5, props.lods[hlod_idx].target_tris_pct / 100.0))
        elif len(props.lod_preset_active_tiers) >= 2:
            lod1_ratio = max(0.01, min(0.99, props.lod_preset_active_tiers[1].target_tris_pct / 100.0))
            hlod_idx = min(len(props.lod_preset_active_tiers) - 1, max(2, int(props.hlod_start_tier)))
            hlod_ratio = max(0.005, min(0.5, props.lod_preset_active_tiers[hlod_idx].target_tris_pct / 100.0))
        return lod1_ratio, hlod_ratio

    def _slice_lod0_chunks(
        self,
        context: Any,
        source_obj: Any,
        grid_spec: SpatialGridSpec,
        base_name: str,
        props: Any,
    ) -> tuple[Any, list[Any]] | None:
        lod0_coll_name = f"{base_name}_Chunks_LOD0"
        lod0_coll = bpy.data.collections.get(lod0_coll_name)
        if not lod0_coll:
            lod0_coll = bpy.data.collections.new(name=lod0_coll_name)
            context.scene.collection.children.link(lod0_coll)

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
            return None

        if not chunk_objs_lod0:
            safe_report(self, {"ERROR"}, "No chunks generated from mesh.")
            return None

        return lod0_coll, chunk_objs_lod0

    @staticmethod
    def _generate_lod1_chunks(
        context: Any,
        chunk_objs_lod0: list[Any],
        lod0_coll: Any,
        base_name: str,
        lod1_ratio: float,
    ) -> tuple[Any, list[Any]]:
        lod1_coll_name = f"{base_name}_Chunks_LOD1"
        lod1_coll = bpy.data.collections.get(lod1_coll_name)
        if not lod1_coll:
            lod1_coll = bpy.data.collections.new(name=lod1_coll_name)
            context.scene.collection.children.link(lod1_coll)

        chunk_objs_lod1: list[Any] = []
        vl = getattr(context, "view_layer", None)
        with LayerCollectionGuard(vl, [lod0_coll, lod1_coll]):
            for chunk_lod0 in chunk_objs_lod0:
                c_data = chunk_lod0.data.copy()
                c_data.name = f"{chunk_lod0.name}_LOD1_Mesh"
                c_obj = bpy.data.objects.new(name=f"{chunk_lod0.name}_LOD1", object_data=c_data)
                c_obj.matrix_world = chunk_lod0.matrix_world.copy()
                lod1_coll.objects.link(c_obj)

                try:
                    MaterialOptimizer.consolidate_micro_materials(c_obj, area_threshold_pct=0.5)
                except Exception as exc:
                    logger.debug("Material consolidation skipped for chunk %s: %s", c_obj.name, exc)

                MeshDecimator.execute_decimate_qem(
                    obj=c_obj,
                    target_ratio=lod1_ratio,
                    use_curvature_weight=True,
                    group_name="OMNIMESH_SEAM_LOCKED",
                    vertex_group_factor=1.0,
                    cleanup_group=False,
                )
                chunk_objs_lod1.append(c_obj)

        return lod1_coll, chunk_objs_lod1

    def _generate_hierarchical_hlod(
        self,
        context: Any,
        chunk_objs_lod1: list[Any],
        base_name: str,
        props: Any,
        grid_spec: SpatialGridSpec,
        use_voxel_shell: bool,
        voxel_size: float,
    ) -> None:
        current_input_chunks = chunk_objs_lod1
        start_tier = max(2, int(props.hlod_start_tier))
        max_tier = len(props.lods) - 1

        for tier_idx in range(start_tier, max_tier + 1):
            tier_ratio = max(0.005, min(0.5, props.lods[tier_idx].target_tris_pct / 100.0))
            is_terminal = tier_idx == max_tier

            hlod_coll_name = f"{base_name}_HLOD_LOD{tier_idx}"
            hlod_coll = bpy.data.collections.get(hlod_coll_name)
            if not hlod_coll:
                hlod_coll = bpy.data.collections.new(name=hlod_coll_name)
                context.scene.collection.children.link(hlod_coll)

            clusters = RecursiveHLODManager.group_chunks_quadtree(
                chunk_objs=current_input_chunks,
                grid_spec=grid_spec,
                stride=2,
            )

            vl = getattr(context, "view_layer", None)
            with LayerCollectionGuard(vl, [hlod_coll]):
                try:
                    tier_hlod_objs = RecursiveHLODManager.build_hierarchical_tier(
                        parent_clusters=clusters,
                        base_name=base_name,
                        tier_index=tier_idx,
                        target_collection=hlod_coll,
                        target_ratio=tier_ratio,
                        weld_dist=0.002,
                        is_terminal_tier=is_terminal,
                        use_voxel_shell=(is_terminal and use_voxel_shell),
                        voxel_size=voxel_size,
                        context=context,
                    )
                    logger.info(
                        "Generated Hierarchical HLOD LOD%d: %d clusters (ratio %.3f)",
                        tier_idx,
                        len(tier_hlod_objs),
                        tier_ratio,
                    )
                    if tier_hlod_objs:
                        current_input_chunks = tier_hlod_objs
                except Exception as exc:
                    logger.error("Hierarchical HLOD tier LOD%d failed: %s", tier_idx, exc, exc_info=True)
                    safe_report(self, {"WARNING"}, f"HLOD tier {tier_idx} failed: {exc}")

    def _generate_flat_hlod(
        self,
        context: Any,
        chunk_objs_lod1: list[Any],
        base_name: str,
        hlod_ratio: float,
    ) -> None:
        hlod_coll_name = f"{base_name}_HLOD_LOD2"
        hlod_coll = bpy.data.collections.get(hlod_coll_name)
        if not hlod_coll:
            hlod_coll = bpy.data.collections.new(name=hlod_coll_name)
            context.scene.collection.children.link(hlod_coll)

        vl = getattr(context, "view_layer", None)
        with LayerCollectionGuard(vl, [hlod_coll]):
            try:
                hlod_obj = HLODClusterMerger.merge_chunks_for_hlod(
                    chunk_objs=chunk_objs_lod1,
                    hlod_name=f"{base_name}_HLOD_LOD2",
                    target_collection=hlod_coll,
                    weld_dist=0.002,
                )
                if hlod_obj:
                    MeshDecimator.execute_decimate_qem(
                        obj=hlod_obj,
                        target_ratio=hlod_ratio,
                        use_curvature_weight=False,
                        cleanup_group=True,
                    )
                    logger.info("Generated flat HLOD mesh: %s (ratio %.3f)", hlod_obj.name, hlod_ratio)
            except Exception as exc:
                logger.error("HLOD cluster merging failed: %s", exc, exc_info=True)
                safe_report(self, {"WARNING"}, f"HLOD merging failed: {exc}")

    def _generate_hlod_tiers(
        self,
        context: Any,
        chunk_objs_lod1: list[Any],
        base_name: str,
        props: Any,
        grid_spec: SpatialGridSpec,
        hlod_ratio: float,
    ) -> None:
        if not (props.enable_hlod and props.hlod_start_tier <= 2):
            return

        use_hierarchical = bool(getattr(props, "enable_hierarchical_hlod", True))
        use_voxel_shell = bool(getattr(props, "hlod_proxy_remesh", False))
        voxel_size = float(getattr(props, "hlod_proxy_voxel_size", 0.5))

        if use_hierarchical and len(props.lods) >= 3:
            self._generate_hierarchical_hlod(
                context=context,
                chunk_objs_lod1=chunk_objs_lod1,
                base_name=base_name,
                props=props,
                grid_spec=grid_spec,
                use_voxel_shell=use_voxel_shell,
                voxel_size=voxel_size,
            )
        else:
            self._generate_flat_hlod(
                context=context,
                chunk_objs_lod1=chunk_objs_lod1,
                base_name=base_name,
                hlod_ratio=hlod_ratio,
            )

    def execute(self, context: Any) -> set[Any]:
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
        if grid_spec.num_cells_x == 1 and grid_spec.num_cells_y == 1 and (not split_z or grid_spec.num_cells_z == 1):
            safe_report(
                self,
                {"WARNING"},
                f"Asset bounds are smaller than cell size ({cell_size:.1f}m). Use standard 'Generate LODs'.",
            )
            return {"CANCELLED"}

        logger.info(
            "Spatial Grid initialized: %dx%d (%d cells total, %.1fm x %.1fm)",
            grid_spec.num_cells_x,
            grid_spec.num_cells_y,
            total_cells,
            grid_spec.cell_size_x,
            grid_spec.cell_size_y,
        )

        # 2. Slice LOD0 Chunks
        lod0_result = self._slice_lod0_chunks(
            context=context,
            source_obj=source_obj,
            grid_spec=grid_spec,
            base_name=base_name,
            props=props,
        )
        if lod0_result is None:
            return {"CANCELLED"}
        lod0_coll, chunk_objs_lod0 = lod0_result

        # 3. Resolve decimation ratios
        lod1_ratio, hlod_ratio = self._resolve_decimation_ratios(props)

        # 4. Generate LOD1 with Seam Protection
        _, chunk_objs_lod1 = self._generate_lod1_chunks(
            context=context,
            chunk_objs_lod0=chunk_objs_lod0,
            lod0_coll=lod0_coll,
            base_name=base_name,
            lod1_ratio=lod1_ratio,
        )

        # 5. Generate HLOD (LOD2+) if enabled
        self._generate_hlod_tiers(
            context=context,
            chunk_objs_lod1=chunk_objs_lod1,
            base_name=base_name,
            props=props,
            grid_spec=grid_spec,
            hlod_ratio=hlod_ratio,
        )

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

    def execute(self, context: Any) -> set[Any]:
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
                ctx = context or getattr(bpy, "context", None)
                if ctx and hasattr(ctx, "temp_override"):
                    with cast(Any, ctx).temp_override(active_object=obj, object=obj, selected_objects=[obj]):
                        bpy.ops.object.voxel_remesh()
                elif ctx and hasattr(ctx, "view_layer") and hasattr(ctx.view_layer, "objects"):
                    ctx.view_layer.objects.active = obj
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
