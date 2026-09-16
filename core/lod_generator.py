"""
OmniMesh Core LOD Generation Engine.
Implements the multi-stage geometry decimation, collection cloning,
modifier evaluation, topological repair, and bone pruning pipeline.
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

try:
    from .decimator import MeshDecimator
    from .hierarchy import CollectionCloneDAG, LayerCollectionGuard, MeshMergeEngine
    from .material_analyzer import MSFSMaterialAnalyzer
    from .materials import MaterialOptimizer
    from .metrics import (
        compute_bounding_sphere,
        compute_coupled_tolerances,
        compute_vertical_fov,
    )
    from .modifiers import ModifierManager
    from .normals import NormalManager
    from .occlusion import HardenedOcclusionCuller
    from .pivot import PivotPreservationEngine
    from .rigging import KinematicBonePruner, WeightSanitizer
    from .sanitizer import MeshSanitizer
    from .slender import SlenderFeatureCuller
except (ImportError, ValueError):
    from core.decimator import MeshDecimator
    from core.hierarchy import CollectionCloneDAG, LayerCollectionGuard, MeshMergeEngine
    from core.material_analyzer import MSFSMaterialAnalyzer
    from core.materials import MaterialOptimizer
    from core.metrics import (
        compute_bounding_sphere,
        compute_coupled_tolerances,
        compute_vertical_fov,
    )
    from core.modifiers import ModifierManager
    from core.normals import NormalManager
    from core.occlusion import HardenedOcclusionCuller
    from core.pivot import PivotPreservationEngine
    from core.rigging import KinematicBonePruner, WeightSanitizer
    from core.sanitizer import MeshSanitizer
    from core.slender import SlenderFeatureCuller


def _count_triangles(mesh_data: Any) -> int:
    """Computes true triangle count in O(1) via loop-poly invariant with safe fallbacks."""
    if not mesh_data:
        return 0
    try:
        loops = getattr(mesh_data, "loops", None)
        polys = getattr(mesh_data, "polygons", None)
        if loops is not None and polys is not None:
            n_loops = len(loops)
            n_polys = len(polys)
            if n_polys == 0:
                return 0
            return max(0, n_loops - 2 * n_polys)
    except (AttributeError, TypeError) as exc:
        logger.debug("Loop-poly triangle count invariant fallback triggered: %s", exc)

    # Safe fallback for bmesh or mock structures
    polys = getattr(mesh_data, "polygons", getattr(mesh_data, "faces", []))
    if not polys:
        return 0
    try:
        first = polys[0]
        if hasattr(first, "vertices"):
            return sum(max(0, len(p.vertices) - 2) for p in polys)
        elif hasattr(first, "verts"):
            return sum(max(0, len(f.verts) - 2) for f in polys)
        return len(polys)
    except (IndexError, AttributeError, TypeError, ReferenceError, RuntimeError):
        return len(polys)


def _compute_lod0_stats(mesh_objs: list[Any]) -> tuple[int, int]:
    """Calculates initial triangle count and material slot count for LOD0."""
    tier_tris = 0
    tier_mats = sum(len(obj.material_slots) for obj in mesh_objs if hasattr(obj, "material_slots"))
    for obj in mesh_objs:
        if ModifierManager.has_unapplied_modifiers(obj):
            eval_mesh, eval_obj = ModifierManager.get_evaluated_mesh(obj, preserve_armature=True)
            if eval_mesh:
                try:
                    tier_tris += _count_triangles(eval_mesh)
                finally:
                    if eval_obj and hasattr(eval_obj, "to_mesh_clear"):
                        eval_obj.to_mesh_clear()
            else:
                tier_tris += _count_triangles(getattr(obj, "data", None))
        else:
            tier_tris += _count_triangles(getattr(obj, "data", None))
    return tier_tris, tier_mats


def _process_merged_tier(
    tier_coll: Any,
    tier: Any,
    tier_idx: int,
    base_name: str,
    mesh_objs: list[Any],
    armature_obj: Any,
    tier_pivot: Any,
    tolerances: dict[str, Any],
    props: Any,
    render: Any,
    radius: float,
    fov_v: float,
    max_influences: int,
) -> tuple[int, int, int, Any]:
    """Processes a merged LOD tier, combining meshes and applying decimation pipeline."""
    merged_name = f"{base_name}_LOD{tier_idx}"
    existing = bpy.data.objects.get(merged_name)
    if existing and existing not in mesh_objs:
        old_mesh = getattr(existing, "data", None)
        bpy.data.objects.remove(existing, do_unlink=True)
        if old_mesh and getattr(old_mesh, "users", 1) == 0 and hasattr(bpy.data, "meshes"):
            try:
                bpy.data.meshes.remove(old_mesh)
            except Exception as exc:
                logger.debug("Failed deallocating orphan mesh %s: %s", getattr(old_mesh, "name", "mesh"), exc)

    tier_obj = MeshMergeEngine.consolidate_and_merge_meshes(
        mesh_objs, merged_name, armature_obj=armature_obj, pivot_obj=tier_pivot
    )
    if tier_obj.name not in tier_coll.objects:
        tier_coll.objects.link(tier_obj)

    culled_slender_count = 0
    bm = bmesh.new()
    try:
        bm.from_mesh(tier_obj.data)
        MeshSanitizer.sanitize_mesh_full(bm, tolerances["epsilon_merge"], tolerances["w_crit"])

        if props.enable_slender_culling:
            res_slender = SlenderFeatureCuller.cull_slender_features(
                bm,
                screen_size_pct=tier.screen_size_pct,
                resolution_y=render.resolution_y,
                root_radius_m=radius,
                tau_sse=props.tau_sse,
            )
            culled_slender_count += res_slender.get("culled_islands", 0)

        if getattr(props, "enable_occlusion_culling", False) and tier_idx >= getattr(props, "occlusion_lod_start", 1):
            HardenedOcclusionCuller.cull_interior_faces(
                tier_obj,
                bm,
                ray_density=getattr(props, "occlusion_ray_density", 16),
                evaluate_alpha=getattr(props, "occlusion_evaluate_alpha", True),
                delta_world=tolerances["delta_world"],
            )

        MeshDecimator.apply_planar_limited_dissolve(bm, math.radians(tolerances["planar_angle_deg"]))
        pinned_verts = MeshDecimator.tag_boundaries_and_uv_seams(
            bm,
            pin_uv_seams=getattr(props, "pin_uv_seams", True),
            pin_material_borders=getattr(props, "pin_material_borders", True),
        )
        MeshDecimator.inject_curvature_weights(tier_obj, bm, pinned_verts)
        bm.to_mesh(tier_obj.data)
    finally:
        bm.free()

    if props.purge_shape_keys and tier_idx >= 2:
        MeshDecimator.prepare_and_clean_shape_keys(tier_obj, purge=True)

    qem_ratio = tier.target_tris_pct / 100.0 if getattr(tier, "target_tris_pct", 0.0) > 0.0 else tolerances["qem_ratio"]
    MeshDecimator.execute_decimate_qem(tier_obj, min(1.0, max(0.001, qem_ratio)), use_curvature_weight=True)

    tier_obj.data.update()
    MaterialOptimizer.consolidate_micro_materials(
        tier_obj,
        area_crit=tolerances["area_crit"],
        preserve_slot_indexing=getattr(props, "preserve_slot_indexing", True),
    )

    # Reproject custom split normals against consolidated source geometry
    ref_merged_obj = None
    try:
        ref_merged_name = f"__OM_Ref_Merged_LOD0_{tier_idx}__"
        ref_merged_obj = MeshMergeEngine.consolidate_and_merge_meshes(
            mesh_objs, ref_merged_name, armature_obj=armature_obj, pivot_obj=tier_pivot
        )
        NormalManager.reproject_custom_split_normals(tier_obj, ref_merged_obj, tolerances["delta_world"])
    except Exception as exc:
        logger.debug("Merged custom split normal reprojection exception: %s", exc)
        if mesh_objs:
            NormalManager.reproject_custom_split_normals(tier_obj, mesh_objs[0], tolerances["delta_world"])
    finally:
        if ref_merged_obj and bpy and hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
            ref_mesh = getattr(ref_merged_obj, "data", None)
            try:
                bpy.data.objects.remove(ref_merged_obj, do_unlink=True)
                if ref_mesh and getattr(ref_mesh, "users", 1) == 0 and hasattr(bpy.data, "meshes"):
                    bpy.data.meshes.remove(ref_mesh)
            except Exception as exc:
                logger.debug("Cleanup ref_merged_obj exception: %s", exc)

    if armature_obj and len(tier_obj.vertex_groups) > 0:
        if props.enable_bone_pruning and tier_idx >= 2:
            KinematicBonePruner.prune_kinematic_subtrees(
                tier_obj,
                armature_obj,
                screen_distance_m=tier.distance_m,
                fov_v_rad=fov_v,
                resolution_y=render.resolution_y,
                pixel_threshold=1.5,
            )
        WeightSanitizer.normalize_and_clamp_weights(tier_obj, max_influences=max_influences)

    tier_obj.data.update()
    actual_tris = _count_triangles(getattr(tier_obj, "data", None))
    actual_mats = len(tier_obj.material_slots)
    if hasattr(tier_obj, "lod_tool"):
        tier_obj.lod_tool.lod_root_object = mesh_objs[0] if mesh_objs else None
        tier_obj.lod_tool.is_generated_lod = True
        tier_obj.lod_tool.lod_index = tier_idx

    return actual_tris, actual_mats, culled_slender_count, tier_obj


def _process_unmerged_tier(
    tier_coll: Any,
    tier: Any,
    tier_idx: int,
    base_name: str,
    mesh_objs: list[Any],
    armature_obj: Any,
    tier_pivot: Any,
    root_pivot: Any,
    tolerances: dict[str, Any],
    props: Any,
    render: Any,
    radius: float,
    fov_v: float,
    max_influences: int,
) -> tuple[int, int, int, Any]:
    """Processes an unmerged multi-mesh LOD tier, decimating each object individually."""
    tier_tris = 0
    tier_mats = 0
    culled_slender_count = 0
    first_generated_obj = None

    for obj_idx, source_obj in enumerate(mesh_objs):
        sub_name = f"{source_obj.name}_LOD{tier_idx}" if len(mesh_objs) > 1 else f"{base_name}_LOD{tier_idx}"
        existing = bpy.data.objects.get(sub_name)
        if existing and existing not in mesh_objs and existing != source_obj:
            old_mesh = getattr(existing, "data", None)
            bpy.data.objects.remove(existing, do_unlink=True)
            if old_mesh and getattr(old_mesh, "users", 1) == 0 and hasattr(bpy.data, "meshes"):
                try:
                    bpy.data.meshes.remove(old_mesh)
                except Exception as exc:
                    logger.debug("Failed deallocating orphan mesh %s: %s", getattr(old_mesh, "name", "mesh"), exc)

        lod_obj = source_obj.copy()
        lod_obj.data = source_obj.data.copy()
        lod_obj.name = sub_name
        lod_obj.data.name = f"{sub_name}_Mesh"
        tier_coll.objects.link(lod_obj)

        if props.purge_shape_keys and tier_idx >= 2:
            MeshDecimator.prepare_and_clean_shape_keys(lod_obj, purge=True)

        ModifierManager.apply_all_modifiers_in_place(lod_obj, preserve_armature=True)

        if tier_pivot:
            is_parent_pivot = (
                lod_obj.parent is None
                or (root_pivot and lod_obj.parent == root_pivot)
                or (root_pivot and getattr(lod_obj.parent, "name", "") == root_pivot.name)
                or "pivot" in getattr(lod_obj.parent, "name", "").lower()
            )
            if is_parent_pivot:
                lod_obj.parent = tier_pivot
                lod_obj.matrix_parent_inverse = source_obj.matrix_parent_inverse.copy()

        bm = bmesh.new()
        try:
            bm.from_mesh(lod_obj.data)
            MeshSanitizer.sanitize_mesh_full(bm, tolerances["epsilon_merge"], tolerances["w_crit"])

            if props.enable_slender_culling:
                res_slender = SlenderFeatureCuller.cull_slender_features(
                    bm,
                    screen_size_pct=tier.screen_size_pct,
                    resolution_y=render.resolution_y,
                    root_radius_m=radius,
                    tau_sse=props.tau_sse,
                )
                culled_slender_count += res_slender.get("culled_islands", 0)

            if getattr(props, "enable_occlusion_culling", False) and tier_idx >= getattr(
                props, "occlusion_lod_start", 1
            ):
                HardenedOcclusionCuller.cull_interior_faces(
                    lod_obj,
                    bm,
                    ray_density=getattr(props, "occlusion_ray_density", 16),
                    evaluate_alpha=getattr(props, "occlusion_evaluate_alpha", True),
                    delta_world=tolerances["delta_world"],
                )

            MeshDecimator.apply_planar_limited_dissolve(bm, math.radians(tolerances["planar_angle_deg"]))
            pinned_verts = MeshDecimator.tag_boundaries_and_uv_seams(
                bm,
                pin_uv_seams=getattr(props, "pin_uv_seams", True),
                pin_material_borders=getattr(props, "pin_material_borders", True),
            )
            MeshDecimator.inject_curvature_weights(lod_obj, bm, pinned_verts)
            bm.to_mesh(lod_obj.data)
        finally:
            bm.free()
        lod_obj.data.update()

        is_decal = False
        if MSFSMaterialAnalyzer:
            is_decal = MSFSMaterialAnalyzer.is_decal_mesh(source_obj)

        qem_ratio = (
            tier.target_tris_pct / 100.0 if getattr(tier, "target_tris_pct", 0.0) > 0.0 else tolerances["qem_ratio"]
        )
        if is_decal and getattr(props, "msfs_preserve_decals", True):
            qem_ratio = max(qem_ratio, 0.75 if tier_idx <= 2 else 0.5)

        MeshDecimator.execute_decimate_qem(lod_obj, min(1.0, max(0.001, qem_ratio)), use_curvature_weight=True)

        MaterialOptimizer.consolidate_micro_materials(
            lod_obj,
            area_crit=tolerances["area_crit"],
            preserve_slot_indexing=props.preserve_slot_indexing,
        )

        NormalManager.reproject_custom_split_normals(lod_obj, source_obj, tolerances["delta_world"])

        if armature_obj and len(lod_obj.vertex_groups) > 0:
            if props.enable_bone_pruning and tier_idx >= 2:
                KinematicBonePruner.prune_kinematic_subtrees(
                    lod_obj,
                    armature_obj,
                    screen_distance_m=tier.distance_m,
                    fov_v_rad=fov_v,
                    resolution_y=render.resolution_y,
                    pixel_threshold=1.5,
                )
            WeightSanitizer.normalize_and_clamp_weights(lod_obj, max_influences=max_influences)

        lod_obj.data.update()
        tier_tris += _count_triangles(getattr(lod_obj, "data", None))
        tier_mats += len(lod_obj.material_slots)
        if hasattr(lod_obj, "lod_tool"):
            lod_obj.lod_tool.lod_root_object = source_obj
            lod_obj.lod_tool.is_generated_lod = True
            lod_obj.lod_tool.lod_index = tier_idx
        if obj_idx == 0:
            first_generated_obj = lod_obj

    return tier_tris, tier_mats, culled_slender_count, first_generated_obj


def generate_all_lods(
    context: Any,
    props: Any,
    mesh_objs: list[Any],
    armature_obj: Any = None,
    base_name: str = "",
    only_out_of_sync: bool = False,
) -> tuple[bool, str]:
    """
    Execute the full multi-tier LOD generation pipeline across selected meshes.

    Performs modifier evaluation, bounding sphere calculation, hierarchical sibling
    collection cloning, mesh merging, geometry sanitization, slender feature culling,
    occlusion face culling, QEM decimation, material slot consolidation, normal
    reprojection, and kinematic bone pruning.

    Args:
        context: Active Blender execution context.
        props: LODToolSettings instance for active asset or scene.
        mesh_objs: List of source LOD0 mesh objects to decimate.
        armature_obj: Optional associated armature object.
        base_name: Resolved base name for the asset.
        only_out_of_sync: When True, skips already baked in-sync tiers.

    Returns:
        tuple[bool, str]: (Success status, descriptive user-facing message).
    """
    if not bpy or not context:
        return True, "Blender context not available."

    if not mesh_objs:
        return False, f"No mesh objects found for asset '{base_name}'."

    orig_pose_pos = None
    if armature_obj and hasattr(armature_obj.data, "pose_position"):
        orig_pose_pos = armature_obj.data.pose_position
        armature_obj.data.pose_position = "REST"

    try:
        base_name = base_name.split("_LOD")[0]

        # 1. Resolve Root Collection or Auto-Wrap Loose Objects
        src_coll = None
        if (
            context.collection
            and context.collection != context.scene.collection
            and context.collection.name == base_name
        ):
            src_coll = context.collection
        elif mesh_objs and getattr(mesh_objs[0], "users_collection", []):
            for c in mesh_objs[0].users_collection:
                if c.name in (base_name, f"{base_name}_LOD0") and c != context.scene.collection:
                    src_coll = c
                    break

        if not src_coll or src_coll.name not in (base_name, f"{base_name}_LOD0"):
            wrap_objs = list(mesh_objs)
            if armature_obj and armature_obj not in wrap_objs:
                wrap_objs.append(armature_obj)
            src_coll, root_pivot = CollectionCloneDAG.wrap_loose_objects_into_root_collection(wrap_objs, base_name)
        else:
            root_pivot, _, _, _ = PivotPreservationEngine.identify_pivots_and_sockets(src_coll)

        all_coords = []
        for obj in mesh_objs:
            if hasattr(obj, "bound_box") and obj.bound_box and Vector is not None:
                all_coords.extend([obj.matrix_world @ Vector(b) for b in obj.bound_box])
            elif hasattr(obj, "data") and hasattr(obj.data, "vertices"):
                all_coords.extend([obj.matrix_world @ v.co for v in obj.data.vertices])
        _, radius = compute_bounding_sphere(all_coords)

        render = context.scene.render
        cam = context.scene.camera
        cam_angle = cam.data.angle if cam and cam.type == "CAMERA" else math.radians(60.0)
        sensor_fit = cam.data.sensor_fit if cam and cam.type == "CAMERA" else "AUTO"
        aspect_ratio = render.resolution_x / max(1, render.resolution_y)
        fov_v = compute_vertical_fov(cam_angle, aspect_ratio, sensor_fit)

        max_influences = int(props.max_bone_influences)

        # Build Sibling Collections list
        all_tier_collections = [src_coll]
        for i in range(1, len(props.lods)):
            tier_c = CollectionCloneDAG.get_or_create_sibling_collection(src_coll, i, base_name)
            all_tier_collections.append(tier_c)

        updated_tier_count = 0

        # Safe View Layer Scoper
        with LayerCollectionGuard(context.view_layer, all_tier_collections):
            for i, tier in enumerate(props.lods):
                if i == 0:
                    tier_tris, tier_mats = _compute_lod0_stats(mesh_objs)
                    tier.actual_tris = tier_tris
                    tier.actual_triangles = tier_tris
                    tier.mat_slots_count = tier_mats
                    tier.generated_obj = mesh_objs[0] if mesh_objs else None
                    tier.state = "SOURCE"
                    continue

                # Check if tier is already baked and in sync when only_out_of_sync is requested
                last_target = getattr(tier, "last_baked_target_pct", -1.0)
                tier_coll = all_tier_collections[i]
                has_mesh_in_scene = bool(tier_coll and getattr(tier_coll, "objects", None))
                is_in_sync = has_mesh_in_scene and last_target > 0.0 and abs(tier.target_tris_pct - last_target) <= 0.01
                if only_out_of_sync and is_in_sync:
                    continue

                updated_tier_count += 1

                # Sibling Collection Tier (LOD1..k)
                dag_info = CollectionCloneDAG.clone_collection_hierarchy(
                    src_coll, tier_coll, i, base_name, armature_obj=armature_obj, pivot_obj=root_pivot
                )
                tier_pivot = dag_info.get("pivot")

                s_frac = tier.screen_size_pct / 100.0
                tolerances = compute_coupled_tolerances(radius, s_frac, props.tau_sse, render.resolution_y)
                should_merge = i >= 1 and (
                    getattr(props, "consolidate_hierarchy", False)
                    or props.hierarchy_mode == "MERGE_ALL"
                    or (props.hierarchy_mode == "MERGE_AT_TIER" and i >= props.merge_start_tier)
                )

                if should_merge and len(mesh_objs) > 1:
                    tris, mats, slender_cull, gen_obj = _process_merged_tier(
                        tier_coll=tier_coll,
                        tier=tier,
                        tier_idx=i,
                        base_name=base_name,
                        mesh_objs=mesh_objs,
                        armature_obj=armature_obj,
                        tier_pivot=tier_pivot,
                        tolerances=tolerances,
                        props=props,
                        render=render,
                        radius=radius,
                        fov_v=fov_v,
                        max_influences=max_influences,
                    )
                else:
                    tris, mats, slender_cull, gen_obj = _process_unmerged_tier(
                        tier_coll=tier_coll,
                        tier=tier,
                        tier_idx=i,
                        base_name=base_name,
                        mesh_objs=mesh_objs,
                        armature_obj=armature_obj,
                        tier_pivot=tier_pivot,
                        root_pivot=root_pivot,
                        tolerances=tolerances,
                        props=props,
                        render=render,
                        radius=radius,
                        fov_v=fov_v,
                        max_influences=max_influences,
                    )

                props.last_culled_slender_count += slender_cull
                tier.actual_tris = tris
                tier.actual_triangles = tris
                tier.mat_slots_count = mats
                tier.generated_obj = gen_obj
                tier.last_baked_target_pct = tier.target_tris_pct
                tier.last_baked_screen_pct = tier.screen_size_pct
                tier.state = "BAKED"

        if len(props.lods) > 0:
            base_tris_val = props.lods[0].actual_tris or props.lods[0].target_tris or 1
            final_tris_val = props.lods[-1].actual_tris or props.lods[-1].target_tris or 1
            reduction_pct = max(0.0, (1.0 - final_tris_val / float(base_tris_val)) * 100.0)

            props.last_generated_base_tris = base_tris_val
            props.last_generated_final_tris = final_tris_val
            props.last_generated_reduction_pct = reduction_pct
            props.last_generated_tier_count = len(props.lods)

        if getattr(props, "enable_impostor_lod", False):
            try:
                if hasattr(bpy.ops.lod_tool, "generate_impostor"):
                    bpy.ops.lod_tool.generate_impostor()
            except Exception as exc:
                logger.debug("Automatic impostor generation skipped: %s", exc)

        if only_out_of_sync:
            msg = f"Successfully updated {updated_tier_count} out-of-sync LOD tier(s) for '{base_name}'"
        else:
            msg = f"Successfully generated {len(props.lods)} Sibling LOD Collections for '{base_name}'"
        return True, msg

    except Exception as exc:
        logger.error("LOD generation failed: %s", exc, exc_info=True)
        return False, f"LOD generation failed: {exc}"

    finally:
        if armature_obj and orig_pose_pos and hasattr(armature_obj.data, "pose_position"):
            armature_obj.data.pose_position = orig_pose_pos


__all__ = ["generate_all_lods"]
