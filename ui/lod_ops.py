"""
Core LOD Generation, Configuration, Tier Preview, and Selection Synchronization Operators.
"""

from __future__ import annotations

import logging
import math
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
    from core.decimator import MeshDecimator
    from core.hierarchy import CollectionCloneDAG, LayerCollectionGuard, MeshMergeEngine
    from core.materials import MaterialOptimizer
    from core.metrics import (
        compute_bounding_sphere,
        compute_coupled_tolerances,
        compute_distance_from_screen_size,
        compute_vertical_fov,
        generate_logarithmic_screen_tiers,
    )
    from core.normals import NormalManager
    from core.occlusion import HardenedOcclusionCuller
    from core.pivot import PivotPreservationEngine
    from core.rigging import KinematicBonePruner, WeightSanitizer
    from core.sanitizer import MeshSanitizer
    from core.slender import SlenderFeatureCuller
    from ui.utils import get_associated_armature, get_selected_mesh_objects, resolve_lod_context, safe_report
except (ImportError, ValueError):
    from ..core.decimator import MeshDecimator
    from ..core.hierarchy import CollectionCloneDAG, LayerCollectionGuard, MeshMergeEngine
    from ..core.materials import MaterialOptimizer
    from ..core.metrics import (
        compute_bounding_sphere,
        compute_coupled_tolerances,
        compute_distance_from_screen_size,
        compute_vertical_fov,
        generate_logarithmic_screen_tiers,
    )
    from ..core.normals import NormalManager
    from ..core.occlusion import HardenedOcclusionCuller
    from ..core.pivot import PivotPreservationEngine
    from ..core.rigging import KinematicBonePruner, WeightSanitizer
    from ..core.sanitizer import MeshSanitizer
    from ..core.slender import SlenderFeatureCuller
    from .utils import get_associated_armature, get_selected_mesh_objects, resolve_lod_context, safe_report


class LOD_OT_analyze_and_configure(Operator):
    """Analyze mesh bounding envelope and initialize logarithmic LOD tiers."""

    bl_idname = "lod_tool.analyze_and_configure"
    bl_label = "Auto-Configure LOD Tiers"
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
            safe_report(self, {"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        all_coords = []
        base_tris = 0
        total_mat_slots = 0

        for obj in mesh_objs:
            base_tris += len(obj.data.polygons)
            total_mat_slots += len(obj.material_slots)
            m_w = obj.matrix_world
            all_coords.extend([m_w @ v.co for v in obj.data.vertices])

        if not all_coords:
            safe_report(self, {"WARNING"}, "Selected meshes contain no vertex coordinates.")
            return {"CANCELLED"}

        center, radius = compute_bounding_sphere(all_coords)

        render = context.scene.render
        cam = context.scene.camera
        cam_angle = cam.data.angle if cam and cam.type == "CAMERA" else math.radians(60.0)
        sensor_fit = cam.data.sensor_fit if cam and cam.type == "CAMERA" else "AUTO"
        aspect_ratio = render.resolution_x / max(1, render.resolution_y)
        fov_v = compute_vertical_fov(cam_angle, aspect_ratio, sensor_fit)

        props.bounding_radius = radius
        props.bounding_center = center
        props.base_triangles = base_tris
        props.screen_coverage_lod0 = 100.0
        props.is_configured = True

        props.lods.clear()
        screen_tiers = generate_logarithmic_screen_tiers(
            num_lods=props.lod_count, cull_screen_size_pct=props.cull_screen_size_pct
        )

        for i, s_pct in enumerate(screen_tiers):
            item = props.lods.add()
            item.name = f"LOD{i}"
            item.lod_index = i
            item.screen_size_pct = s_pct

            s_frac = s_pct / 100.0
            dist = compute_distance_from_screen_size(radius, s_frac, fov_v)
            tolerances = compute_coupled_tolerances(radius, s_frac, props.tau_sse, render.resolution_y)

            item.distance_m = dist
            item.delta_world = tolerances["delta_world"]
            item.target_tris = max(12, int(base_tris * tolerances["qem_ratio"]))
            item.triangle_target = item.target_tris
            item.mat_slots_count = total_mat_slots if i < 2 else max(1, total_mat_slots - (i - 1))

        props.active_lod_index = 0
        safe_report(
            self,
            {"INFO"},
            f"Configured {len(props.lods)} LOD tiers for {len(mesh_objs)} meshes (Radius: {radius:.2f}m, Base Tris: {base_tris:,})",
        )
        return {"FINISHED"}


class LOD_OT_generate_all(Operator):
    """Generate all configured LOD tiers as Sibling Collections with QEM simplification and normal reprojection."""

    bl_idname = "lod_tool.generate_all"
    bl_label = "Generate All LODs"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        props, _, _ = resolve_lod_context(context)
        return bool(context and get_selected_mesh_objects(context) and props and len(props.lods) > 0)

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, target_obj, is_deriv = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        mesh_objs = get_selected_mesh_objects(context)
        armature_obj = get_associated_armature(mesh_objs)

        orig_pose_pos = None
        if armature_obj and hasattr(armature_obj.data, "pose_position"):
            orig_pose_pos = armature_obj.data.pose_position
            armature_obj.data.pose_position = "REST"

        try:
            base_name = props.export_base_name or (
                context.active_object.name if context.active_object else mesh_objs[0].name
            )
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

            # Safe View Layer Scoper
            with LayerCollectionGuard(context.view_layer, all_tier_collections):
                for i, tier in enumerate(props.lods):
                    s_frac = tier.screen_size_pct / 100.0
                    tolerances = compute_coupled_tolerances(radius, s_frac, props.tau_sse, render.resolution_y)
                    should_merge = props.hierarchy_mode == "MERGE_AT_TIER" and i >= props.merge_start_tier

                    tier_coll = all_tier_collections[i]

                    if i == 0:
                        tier_tris = sum(len(obj.data.polygons) for obj in mesh_objs)
                        tier_mats = sum(len(obj.material_slots) for obj in mesh_objs)
                        tier.actual_tris = tier_tris
                        tier.actual_triangles = tier_tris
                        tier.mat_slots_count = tier_mats
                        tier.generated_obj = mesh_objs[0] if mesh_objs else None
                        continue

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
                            pinned_verts = MeshDecimator.tag_boundaries_and_uv_seams(bm)
                            MeshDecimator.apply_planar_limited_dissolve(
                                bm, math.radians(tolerances["planar_angle_deg"])
                            )
                            MeshDecimator.inject_curvature_weights(tier_obj, bm, pinned_verts)
                            bm.to_mesh(tier_obj.data)
                        finally:
                            bm.free()
                        tier_obj.data.update()

                        MeshDecimator.execute_decimate_qem(tier_obj, tolerances["qem_ratio"], use_curvature_weight=True)

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
                                        protect_silhouettes=props.preserve_silhouette,
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

                                pinned_verts = MeshDecimator.tag_boundaries_and_uv_seams(bm)
                                MeshDecimator.apply_planar_limited_dissolve(
                                    bm, math.radians(tolerances["planar_angle_deg"])
                                )
                                MeshDecimator.inject_curvature_weights(lod_obj, bm, pinned_verts)
                                bm.to_mesh(lod_obj.data)
                            finally:
                                bm.free()
                            lod_obj.data.update()

                            MeshDecimator.execute_decimate_qem(
                                lod_obj, tolerances["qem_ratio"], use_curvature_weight=True
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
                            if obj_idx == 0:
                                tier.generated_obj = lod_obj

                        tier.actual_tris = tier_tris
                        tier.actual_triangles = tier_tris
                        tier.mat_slots_count = tier_mats

            if len(props.lods) > 0:
                base_tris_val = props.lods[0].actual_tris or props.lods[0].target_tris or 1
                final_tris_val = props.lods[-1].actual_tris or props.lods[-1].target_tris or 1
                reduction_pct = max(0.0, (1.0 - final_tris_val / float(base_tris_val)) * 100.0)

                props.last_generated_base_tris = base_tris_val
                props.last_generated_final_tris = final_tris_val
                props.last_generated_reduction_pct = reduction_pct
                props.last_generated_tier_count = len(props.lods)

            safe_report(
                self, {"INFO"}, f"Successfully generated {len(props.lods)} Sibling LOD Collections for '{base_name}'"
            )
            return {"FINISHED"}
        finally:
            if armature_obj and orig_pose_pos and hasattr(armature_obj.data, "pose_position"):
                armature_obj.data.pose_position = orig_pose_pos


class LOD_OT_preview_tier(Operator):
    """Isolate and display selected LOD tier geometry in 3D Viewport."""

    bl_idname = "lod_tool.preview_tier"
    bl_label = "Preview Selected Tier"
    bl_options = {"REGISTER", "UNDO"}

    tier_index: bpy.props.IntProperty(default=0) if bpy else 0

    def execute(self, context: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        target_idx = int(self.tier_index)
        props.active_lod_index = target_idx

        base_name = props.export_base_name or (context.active_object.name if context.active_object else "Asset")
        base_name = base_name.split("_LOD")[0]

        for i in range(len(props.lods)):
            c_name = f"{base_name}_LOD{i}" if i > 0 else base_name
            coll = bpy.data.collections.get(c_name)
            if coll:
                coll.hide_viewport = target_idx >= 0 and i != target_idx

        safe_report(self, {"INFO"}, f"Previewing LOD Tier: LOD{target_idx}")
        return {"FINISHED"}


class LOD_OT_sync_selection_settings(Operator):
    """Copy LOD tool settings from active master mesh to all selected objects."""

    bl_idname = "lod_tool.sync_selection_settings"
    bl_label = "Copy Settings to Selection"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        props, target_obj, _ = resolve_lod_context(context)
        if not props or not target_obj:
            return {"FINISHED"}

        copied = 0
        for obj in context.selected_objects:
            if obj != target_obj and getattr(obj, "type", "") == "MESH" and hasattr(obj, "lod_tool"):
                other_props = obj.lod_tool
                other_props.asset_category = props.asset_category
                other_props.progression_mode = props.progression_mode
                other_props.lod_count = props.lod_count
                other_props.tau_sse = props.tau_sse
                other_props.preserve_silhouette = props.preserve_silhouette
                other_props.pin_uv_seams = props.pin_uv_seams
                other_props.enable_slender_culling = props.enable_slender_culling
                other_props.is_configured = True
                copied += 1

        safe_report(self, {"INFO"}, f"Synchronized settings across {copied} object(s).")
        return {"FINISHED"}


class LOD_OT_select_master_asset(Operator):
    """Select and focus root master asset in 3D Viewport."""

    bl_idname = "lod_tool.select_master_asset"
    bl_label = "Select Master Asset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        active_obj = context.active_object
        if not active_obj or not hasattr(active_obj, "lod_tool"):
            return {"CANCELLED"}

        master_name = active_obj.lod_tool.lod_root_object
        master_obj = bpy.data.objects.get(master_name)
        if master_obj:
            bpy.ops.object.select_all(action="DESELECT")
            master_obj.select_set(True)
            context.view_layer.objects.active = master_obj
            safe_report(self, {"INFO"}, f"Selected master asset: {master_name}")
            return {"FINISHED"}

        return {"CANCELLED"}


LOD_OPERATOR_CLASSES = (
    LOD_OT_analyze_and_configure,
    LOD_OT_generate_all,
    LOD_OT_preview_tier,
    LOD_OT_sync_selection_settings,
    LOD_OT_select_master_asset,
)
