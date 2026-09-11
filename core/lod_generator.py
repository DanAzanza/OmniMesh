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
    from core.decimator import MeshDecimator
    from core.hierarchy import CollectionCloneDAG, LayerCollectionGuard, MeshMergeEngine
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
except (ImportError, ValueError):
    from .decimator import MeshDecimator
    from .hierarchy import CollectionCloneDAG, LayerCollectionGuard, MeshMergeEngine
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
                if c.name == base_name and c != context.scene.collection:
                    src_coll = c
                    break

        # Normalize rotation and scale on unparented meshes before creating root pivot
        for obj in mesh_objs:
            if not obj.parent:
                try:
                    bpy.context.view_layer.objects.active = obj
                    obj.select_set(True)
                    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
                except Exception as exc:
                    logger.debug("Transform apply skipped for %s: %s", getattr(obj, "name", "obj"), exc)

        if not src_coll or src_coll.name != base_name:
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
                s_frac = tier.screen_size_pct / 100.0
                tolerances = compute_coupled_tolerances(radius, s_frac, props.tau_sse, render.resolution_y)
                should_merge = i >= 1 and (
                    getattr(props, "consolidate_hierarchy", False)
                    or props.hierarchy_mode == "MERGE_ALL"
                    or (props.hierarchy_mode == "MERGE_AT_TIER" and i >= props.merge_start_tier)
                )

                tier_coll = all_tier_collections[i]

                if i == 0:
                    tier_tris = 0
                    tier_mats = sum(len(obj.material_slots) for obj in mesh_objs)
                    for obj in mesh_objs:
                        if ModifierManager.has_unapplied_modifiers(obj):
                            eval_mesh, eval_obj = ModifierManager.get_evaluated_mesh(obj, preserve_armature=True)
                            if eval_mesh:
                                tier_tris += len(getattr(eval_mesh, "polygons", []))
                                if eval_obj and hasattr(eval_obj, "to_mesh_clear"):
                                    eval_obj.to_mesh_clear()
                            else:
                                tier_tris += len(obj.data.polygons)
                        else:
                            tier_tris += len(obj.data.polygons)
                    tier.actual_tris = tier_tris
                    tier.actual_triangles = tier_tris
                    tier.mat_slots_count = tier_mats
                    tier.generated_obj = mesh_objs[0] if mesh_objs else None
                    tier.state = "SOURCE"
                    continue

                # Check if tier is already baked and in sync when only_out_of_sync is requested
                last_target = getattr(tier, "last_baked_target_pct", -1.0)
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

                if should_merge and len(mesh_objs) > 1:
                    merged_name = f"{base_name}_LOD{i}"
                    existing = bpy.data.objects.get(merged_name)
                    if existing and existing not in mesh_objs:
                        bpy.data.objects.remove(existing, do_unlink=True)

                    tier_obj = MeshMergeEngine.consolidate_and_merge_meshes(
                        mesh_objs, merged_name, armature_obj=armature_obj, pivot_obj=tier_pivot
                    )
                    if tier_obj.name not in tier_coll.objects:
                        tier_coll.objects.link(tier_obj)

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
                            props.last_culled_slender_count += res_slender.get("culled_islands", 0)

                        if getattr(props, "enable_occlusion_culling", False) and i >= getattr(
                            props, "occlusion_lod_start", 1
                        ):
                            HardenedOcclusionCuller.cull_interior_faces(
                                tier_obj,
                                bm,
                                ray_density=getattr(props, "occlusion_ray_density", 16),
                                evaluate_alpha=getattr(props, "occlusion_evaluate_alpha", True),
                                delta_world=tolerances["delta_world"],
                            )

                        pinned_verts = MeshDecimator.tag_boundaries_and_uv_seams(
                            bm,
                            pin_uv_seams=getattr(props, "pin_uv_seams", True),
                            pin_material_borders=getattr(props, "pin_material_borders", True),
                        )
                        MeshDecimator.apply_planar_limited_dissolve(bm, math.radians(tolerances["planar_angle_deg"]))
                        MeshDecimator.inject_curvature_weights(tier_obj, bm, pinned_verts)
                        bm.to_mesh(tier_obj.data)
                    finally:
                        bm.free()
                    qem_ratio = (
                        tier.target_tris_pct / 100.0
                        if getattr(tier, "target_tris_pct", 0.0) > 0.0
                        else tolerances["qem_ratio"]
                    )
                    MeshDecimator.execute_decimate_qem(
                        tier_obj, min(1.0, max(0.001, qem_ratio)), use_curvature_weight=True
                    )

                    if props.purge_shape_keys and i >= 2:
                        MeshDecimator.prepare_and_clean_shape_keys(tier_obj, purge=True)

                    if armature_obj and len(tier_obj.vertex_groups) > 0:
                        if props.enable_bone_pruning and i >= 2:
                            KinematicBonePruner.prune_kinematic_subtrees(
                                tier_obj,
                                armature_obj,
                                screen_distance_m=tier.distance_m,
                                fov_v_rad=fov_v,
                                resolution_y=render.resolution_y,
                                pixel_threshold=1.5,
                            )
                        WeightSanitizer.normalize_and_clamp_weights(tier_obj, max_influences=max_influences)

                    tier.actual_tris = len(tier_obj.data.polygons)
                    tier.actual_triangles = tier.actual_tris
                    tier.mat_slots_count = len(tier_obj.material_slots)
                    if hasattr(tier_obj, "lod_tool"):
                        tier_obj.lod_tool.lod_root_object = mesh_objs[0] if mesh_objs else None
                        tier_obj.lod_tool.is_generated_lod = True
                        tier_obj.lod_tool.lod_index = i
                    tier.generated_obj = tier_obj

                else:
                    tier_tris = 0
                    tier_mats = 0
                    for obj_idx, source_obj in enumerate(mesh_objs):
                        sub_name = f"{source_obj.name}_LOD{i}" if len(mesh_objs) > 1 else f"{base_name}_LOD{i}"
                        existing = bpy.data.objects.get(sub_name)
                        if existing and existing not in mesh_objs and existing != source_obj:
                            bpy.data.objects.remove(existing, do_unlink=True)

                        lod_obj = source_obj.copy()
                        lod_obj.data = source_obj.data.copy()
                        lod_obj.name = sub_name
                        lod_obj.data.name = f"{sub_name}_Mesh"
                        tier_coll.objects.link(lod_obj)

                        # Bake procedural modifiers so LOD operations run on evaluated geometry
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

                        if props.purge_shape_keys and i >= 2:
                            MeshDecimator.prepare_and_clean_shape_keys(lod_obj, purge=True)

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
                                props.last_culled_slender_count += res_slender.get("culled_islands", 0)

                            if getattr(props, "enable_occlusion_culling", False) and i >= getattr(
                                props, "occlusion_lod_start", 1
                            ):
                                HardenedOcclusionCuller.cull_interior_faces(
                                    lod_obj,
                                    bm,
                                    ray_density=getattr(props, "occlusion_ray_density", 16),
                                    evaluate_alpha=getattr(props, "occlusion_evaluate_alpha", True),
                                    delta_world=tolerances["delta_world"],
                                )

                            pinned_verts = MeshDecimator.tag_boundaries_and_uv_seams(
                                bm,
                                pin_uv_seams=getattr(props, "pin_uv_seams", True),
                                pin_material_borders=getattr(props, "pin_material_borders", True),
                            )
                            MeshDecimator.apply_planar_limited_dissolve(
                                bm, math.radians(tolerances["planar_angle_deg"])
                            )
                            MeshDecimator.inject_curvature_weights(lod_obj, bm, pinned_verts)
                            bm.to_mesh(lod_obj.data)
                        finally:
                            bm.free()
                        lod_obj.data.update()

                        qem_ratio = (
                            tier.target_tris_pct / 100.0
                            if getattr(tier, "target_tris_pct", 0.0) > 0.0
                            else tolerances["qem_ratio"]
                        )
                        MeshDecimator.execute_decimate_qem(
                            lod_obj, min(1.0, max(0.001, qem_ratio)), use_curvature_weight=True
                        )

                        MaterialOptimizer.consolidate_micro_materials(
                            lod_obj,
                            area_crit=tolerances["area_crit"],
                            preserve_slot_indexing=props.preserve_slot_indexing,
                        )

                        NormalManager.reproject_custom_split_normals(lod_obj, source_obj, tolerances["delta_world"])

                        if armature_obj and len(lod_obj.vertex_groups) > 0:
                            if props.enable_bone_pruning and i >= 2:
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
                        tier_tris += len(lod_obj.data.polygons)
                        tier_mats += len(lod_obj.material_slots)
                        if hasattr(lod_obj, "lod_tool"):
                            lod_obj.lod_tool.lod_root_object = source_obj
                            lod_obj.lod_tool.is_generated_lod = True
                            lod_obj.lod_tool.lod_index = i
                        if obj_idx == 0:
                            tier.generated_obj = lod_obj

                    tier.actual_tris = tier_tris
                    tier.actual_triangles = tier_tris
                    tier.mat_slots_count = tier_mats
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
