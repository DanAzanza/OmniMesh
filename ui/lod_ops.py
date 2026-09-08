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
    from mathutils import Vector
except ImportError:
    bpy = None
    bmesh = None
    Operator = object
    Vector = None

try:
    from core.decimator import MeshDecimator
    from core.hierarchy import CollectionCloneDAG, LayerCollectionGuard, MeshMergeEngine
    from core.materials import MaterialOptimizer
    from core.metrics import (
        compute_bounding_sphere,
        compute_coupled_tolerances,
        compute_distance_from_screen_size,
        compute_vertical_fov,
    )
    from core.modifiers import ModifierManager
    from core.normals import NormalManager
    from core.occlusion import HardenedOcclusionCuller
    from core.pivot import PivotPreservationEngine
    from core.rigging import KinematicBonePruner, WeightSanitizer
    from core.sanitizer import MeshSanitizer
    from core.slender import SlenderFeatureCuller
    from ui.properties import project_preset_tiers
    from ui.utils import (
        get_asset_base_meshes,
        get_associated_armature,
        get_selected_mesh_objects,
        resolve_effective_asset_name,
        resolve_lod_context,
        safe_report,
    )
except (ImportError, ValueError):
    from ..core.decimator import MeshDecimator
    from ..core.hierarchy import CollectionCloneDAG, LayerCollectionGuard, MeshMergeEngine
    from ..core.materials import MaterialOptimizer
    from ..core.metrics import (
        compute_bounding_sphere,
        compute_coupled_tolerances,
        compute_distance_from_screen_size,
        compute_vertical_fov,
    )
    from ..core.modifiers import ModifierManager
    from ..core.normals import NormalManager
    from ..core.occlusion import HardenedOcclusionCuller
    from ..core.pivot import PivotPreservationEngine
    from ..core.rigging import KinematicBonePruner, WeightSanitizer
    from ..core.sanitizer import MeshSanitizer
    from ..core.slender import SlenderFeatureCuller
    from .properties import project_preset_tiers
    from .utils import (
        get_asset_base_meshes,
        get_associated_armature,
        get_selected_mesh_objects,
        resolve_effective_asset_name,
        resolve_lod_context,
        safe_report,
    )


class LOD_OT_reset_to_preset(Operator):
    """Reset LOD tiers and parameters to the active preset defaults."""

    bl_idname = "lod_tool.reset_to_preset"
    bl_label = "Reset to Preset"
    bl_description = "Resets all tier budgets and transition metrics back to the active preset defaults"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        project_preset_tiers(props, context)
        props.lod_preset_is_dirty = False
        safe_report(self, {"INFO"}, "Reset tiers to preset defaults.")
        return {"FINISHED"}


class LOD_OT_analyze_and_configure(Operator):
    """Analyze mesh bounding envelope and initialize logarithmic LOD tiers."""

    bl_idname = "lod_tool.analyze_and_configure"
    bl_label = "Auto-Configure LOD Tiers"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = getattr(getattr(context, "scene", None), "lod_tool", None)
        asset_name = resolve_effective_asset_name(context, props)
        meshes = get_asset_base_meshes(context, asset_name) if asset_name else []
        return bool(context and (meshes or get_selected_mesh_objects(context)))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, target_obj, is_deriv = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        project_preset_tiers(props, context)
        safe_report(
            self,
            {"INFO"},
            f"Configured {len(props.lods)} LOD tiers for '{props.export_base_name}' (Radius: {props.bounding_radius:.2f}m, Base Tris: {props.base_triangles:,})",
        )
        return {"FINISHED"}


class LOD_OT_generate_all(Operator):
    """Generate all configured LOD tiers as Sibling Collections with QEM simplification and normal reprojection."""

    bl_idname = "lod_tool.generate_all"
    bl_label = "Generate All LODs"
    bl_options = {"REGISTER", "UNDO"}

    only_out_of_sync: (
        bpy.props.BoolProperty(
            name="Only Out of Sync",
            default=False,
            description="When enabled, skips already baked and synchronized tiers, regenerating only out-of-sync or planned tiers",
        )
        if bpy
        else False
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = getattr(getattr(context, "scene", None), "lod_tool", None)
        asset_name = resolve_effective_asset_name(context, props)
        meshes = get_asset_base_meshes(context, asset_name) if asset_name else []
        return bool(context and (meshes or get_selected_mesh_objects(context)) and props and len(props.lods) > 0)

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, target_obj, is_deriv = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        asset_name = resolve_effective_asset_name(context, props)
        mesh_objs = get_asset_base_meshes(context, asset_name) if asset_name else []
        if not mesh_objs:
            mesh_objs = get_selected_mesh_objects(context)

        if not mesh_objs:
            safe_report(self, {"WARNING"}, f"No mesh objects found for asset '{asset_name}'.")
            return {"CANCELLED"}

        armature_obj = get_associated_armature(mesh_objs)

        orig_pose_pos = None
        if armature_obj and hasattr(armature_obj.data, "pose_position"):
            orig_pose_pos = armature_obj.data.pose_position
            armature_obj.data.pose_position = "REST"

        try:
            base_name = (
                asset_name
                or props.export_base_name
                or (context.active_object.name if context.active_object else mesh_objs[0].name)
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
                    should_merge = props.hierarchy_mode == "MERGE_AT_TIER" and i >= props.merge_start_tier

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
                    is_in_sync = (
                        has_mesh_in_scene and last_target > 0.0 and abs(tier.target_tris_pct - last_target) <= 0.01
                    )
                    if self.only_out_of_sync and is_in_sync:
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
                                    protect_silhouettes=props.preserve_silhouette,
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
                            MeshDecimator.apply_planar_limited_dissolve(
                                bm, math.radians(tolerances["planar_angle_deg"])
                            )
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

            if self.only_out_of_sync:
                safe_report(
                    self,
                    {"INFO"},
                    f"Successfully updated {updated_tier_count} out-of-sync LOD tier(s) for '{base_name}'",
                )
            else:
                safe_report(
                    self,
                    {"INFO"},
                    f"Successfully generated {len(props.lods)} Sibling LOD Collections for '{base_name}'",
                )
            return {"FINISHED"}
        finally:
            if armature_obj and orig_pose_pos and hasattr(armature_obj.data, "pose_position"):
                armature_obj.data.pose_position = orig_pose_pos


class LOD_OT_solo_tier(Operator):
    """Isolate selected LOD tier in 3D Viewport or restore default visibility."""

    bl_idname = "lod_tool.solo_tier"
    bl_label = "Solo LOD Tier"
    bl_description = "Isolates the selected LOD tier in 3D Viewport. Click again to restore standard visibility"
    bl_options = {"REGISTER", "UNDO"}

    tier_index: bpy.props.IntProperty(name="Tier Index", default=0) if bpy else 0

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        target_idx = int(self.tier_index)
        if not props.lods or target_idx < 0 or target_idx >= len(props.lods):
            return {"CANCELLED"}

        target_tier = props.lods[target_idx]
        already_soloed = getattr(target_tier, "is_soloed", False)

        base_name = props.export_base_name or (context.active_object.name if context.active_object else "Asset")
        base_name = base_name.split("_LOD")[0]
        view_layer = context.view_layer

        if already_soloed:
            # UN-SOLO: Restore standard visibility (LOD0 shown, LOD1..k hidden)
            for i, itm in enumerate(props.lods):
                itm.is_soloed = False
                c_name = f"{base_name}_LOD{i}" if i > 0 else base_name
                coll = bpy.data.collections.get(c_name)
                if coll:
                    for obj in coll.all_objects:
                        obj.hide_set(i != 0, view_layer=view_layer)
            safe_report(self, {"INFO"}, "Un-soloed: Default scene visibility restored (LOD0 visible).")
        else:
            # SOLO: Isolate target_idx
            for i, itm in enumerate(props.lods):
                is_target = i == target_idx
                itm.is_soloed = is_target
                c_name = f"{base_name}_LOD{i}" if i > 0 else base_name
                coll = bpy.data.collections.get(c_name)
                if coll:
                    for obj in coll.all_objects:
                        obj.hide_set(not is_target, view_layer=view_layer)

            props.active_lod_index = target_idx
            if target_tier.generated_obj and target_tier.generated_obj.name in bpy.data.objects:
                try:
                    view_layer.objects.active = target_tier.generated_obj
                except Exception as exc:
                    logger.debug("Failed setting active object during solo: %s", exc)

            safe_report(self, {"INFO"}, f"Soloing {target_tier.name}")

        if hasattr(context, "screen") and context.screen:
            for area in context.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()

        return {"FINISHED"}


class LOD_OT_add_lod_tier(Operator):
    """Append a new LOD tier to the active configuration."""

    bl_idname = "lod_tool.add_lod_tier"
    bl_label = "Add LOD Tier"
    bl_description = "Appends a new LOD tier to the current configuration"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        if len(props.lods) >= 8:
            safe_report(self, {"WARNING"}, "Maximum 8 LOD tiers supported.")
            return {"CANCELLED"}

        new_idx = len(props.lods)
        if new_idx > 0:
            prev = props.lods[new_idx - 1]
            s_pct = max(1.0, round(prev.screen_size_pct * 0.5, 1))
            tris_pct = max(2.0, round(prev.target_tris_pct * 0.5, 1))
        else:
            s_pct = 100.0
            tris_pct = 100.0

        item = props.lods.add()
        item.name = f"LOD{new_idx}"
        item.lod_index = new_idx
        item.screen_size_pct = s_pct
        item.target_tris_pct = tris_pct
        item.is_soloed = False

        if props.base_triangles > 0:
            item.target_tris = max(12, int(props.base_triangles * (tris_pct / 100.0)))
            item.triangle_target = item.target_tris

        if props.bounding_radius > 0:
            render = context.scene.render
            cam = context.scene.camera
            cam_angle = cam.data.angle if cam and cam.type == "CAMERA" else math.radians(60.0)
            sensor_fit = cam.data.sensor_fit if cam and cam.type == "CAMERA" else "AUTO"
            aspect_ratio = render.resolution_x / max(1, render.resolution_y)
            fov_v = compute_vertical_fov(cam_angle, aspect_ratio, sensor_fit)
            dist = compute_distance_from_screen_size(props.bounding_radius, s_pct / 100.0, fov_v)
            item.distance_m = dist

        props.active_lod_index = new_idx
        safe_report(self, {"INFO"}, f"Added {item.name}.")
        return {"FINISHED"}


class LOD_OT_remove_lod_tier(Operator):
    """Remove the active or specified LOD tier from configuration."""

    bl_idname = "lod_tool.remove_lod_tier"
    bl_label = "Remove LOD Tier"
    bl_description = "Removes the selected LOD tier from configuration"
    bl_options = {"REGISTER", "UNDO"}

    tier_index: bpy.props.IntProperty(name="Tier Index", default=-1) if bpy else -1

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        if len(props.lods) <= 1:
            safe_report(self, {"WARNING"}, "Cannot remove base tier (LOD0).")
            return {"CANCELLED"}

        if self.tier_index >= 0 and self.tier_index < len(props.lods):
            target_idx = self.tier_index
        elif props.active_lod_index > 0:
            target_idx = props.active_lod_index
        else:
            target_idx = len(props.lods) - 1

        if target_idx == 0:
            safe_report(self, {"WARNING"}, "Cannot remove base tier (LOD0).")
            return {"CANCELLED"}

        removed_name = props.lods[target_idx].name
        props.lods.remove(target_idx)

        for idx, itm in enumerate(props.lods):
            itm.lod_index = idx
            if itm.name.startswith("LOD"):
                itm.name = f"LOD{idx}"

        props.active_lod_index = min(target_idx, len(props.lods) - 1)
        safe_report(self, {"INFO"}, f"Removed {removed_name}.")
        return {"FINISHED"}


class LOD_OT_preview_tier(Operator):
    """Isolate and display selected LOD tier geometry in 3D Viewport."""

    bl_idname = "lod_tool.preview_tier"
    bl_label = "Preview Selected Tier"
    bl_options = {"REGISTER", "UNDO"}

    tier_index: bpy.props.IntProperty(default=0) if bpy else 0

    def execute(self, context: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        return bpy.ops.lod_tool.solo_tier(tier_index=int(self.tier_index))


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
                other_props.pin_material_borders = props.pin_material_borders
                other_props.enable_slender_culling = props.enable_slender_culling
                other_props.enable_occlusion_culling = props.enable_occlusion_culling
                other_props.occlusion_lod_start = props.occlusion_lod_start
                other_props.occlusion_ray_density = props.occlusion_ray_density
                other_props.occlusion_evaluate_alpha = props.occlusion_evaluate_alpha
                other_props.enable_impostor_lod = props.enable_impostor_lod
                other_props.impostor_mode = props.impostor_mode
                other_props.impostor_resolution = props.impostor_resolution
                other_props.impostor_replace_last_lod = props.impostor_replace_last_lod
                other_props.enable_spatial_chunking = props.enable_spatial_chunking
                other_props.chunk_cell_size = props.chunk_cell_size
                other_props.chunk_split_z = props.chunk_split_z
                other_props.chunk_cell_size_z = props.chunk_cell_size_z
                other_props.chunk_partitioning_mode = props.chunk_partitioning_mode
                other_props.adaptive_cluster_target_polys = props.adaptive_cluster_target_polys
                other_props.enable_hlod = props.enable_hlod
                other_props.hlod_start_tier = props.hlod_start_tier
                other_props.lod_preset = props.lod_preset
                other_props.lod_preset_budget_mode = props.lod_preset_budget_mode

                # Sync active preset tiers collection
                if hasattr(other_props, "lod_preset_active_tiers"):
                    other_props.lod_preset_active_tiers.clear()
                    for tier in props.lod_preset_active_tiers:
                        t = other_props.lod_preset_active_tiers.add()
                        t.name = tier.name
                        t.screen_size_pct = tier.screen_size_pct
                        t.target_tris_pct = tier.target_tris_pct
                        t.target_tris = tier.target_tris

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

        master_val = active_obj.lod_tool.lod_root_object
        master_obj = None
        if isinstance(master_val, str):
            master_obj = bpy.data.objects.get(master_val)
        elif hasattr(master_val, "name") and master_val.name in bpy.data.objects:
            master_obj = master_val

        if master_obj:
            bpy.ops.object.select_all(action="DESELECT")
            master_obj.select_set(True)
            context.view_layer.objects.active = master_obj
            safe_report(self, {"INFO"}, f"Selected master asset: {master_obj.name}")
            return {"FINISHED"}

        return {"CANCELLED"}


class LOD_OT_add_preset_tier(Operator):
    """Append a new tier template to the active LOD preset."""

    bl_idname = "lod_tool.add_preset_tier"
    bl_label = "Add Preset Tier"
    bl_description = "Appends a new tier template to the current preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        if len(props.lod_preset_active_tiers) >= 8:
            safe_report(self, {"WARNING"}, "Maximum 8 LOD tiers supported in a preset.")
            return {"CANCELLED"}

        count = len(props.lod_preset_active_tiers)
        prev = props.lod_preset_active_tiers[count - 1] if count > 0 else None

        item = props.lod_preset_active_tiers.add()
        item.name = f"LOD{count}"
        item.screen_size_pct = max(0.1, round(prev.screen_size_pct * 0.5, 1)) if prev else 100.0
        item.target_tris_pct = max(0.01, round(prev.target_tris_pct * 0.5, 2)) if prev else 100.0
        item.target_tris = max(6, int(prev.target_tris * 0.5)) if prev else 100000

        props.lod_preset_active_tier_index = count
        props.lod_preset_is_dirty = True
        safe_report(self, {"INFO"}, f"Added preset tier {item.name}.")
        return {"FINISHED"}


class LOD_OT_remove_preset_tier(Operator):
    """Remove the selected tier template from the active LOD preset."""

    bl_idname = "lod_tool.remove_preset_tier"
    bl_label = "Remove Preset Tier"
    bl_description = "Removes the selected tier template from the current preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        count = len(props.lod_preset_active_tiers)
        if count <= 1:
            safe_report(self, {"WARNING"}, "A preset must contain at least one LOD tier.")
            return {"CANCELLED"}

        idx = props.lod_preset_active_tier_index
        if idx < 0 or idx >= count:
            idx = count - 1

        deleted_name = props.lod_preset_active_tiers[idx].name
        props.lod_preset_active_tiers.remove(idx)
        props.lod_preset_active_tier_index = max(0, min(idx, len(props.lod_preset_active_tiers) - 1))
        props.lod_preset_is_dirty = True
        safe_report(self, {"INFO"}, f"Removed preset tier {deleted_name}.")
        return {"FINISHED"}


class LOD_OT_save_preset_tiers(Operator):
    """Save modified tier configuration into the custom LOD preset on disk."""

    bl_idname = "lod_tool.save_preset_tiers"
    bl_label = "Save Preset Tiers"
    bl_description = "Saves tier screensizes and budgets to the custom preset JSON file"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        try:
            try:
                from ui.properties import sync_preset_tiers_to_preset
            except ImportError:
                from .properties import sync_preset_tiers_to_preset

            saved_id = sync_preset_tiers_to_preset(props)
            safe_report(self, {"INFO"}, f"Saved tiers to preset '{saved_id}'.")
            return {"FINISHED"}
        except Exception as exc:
            logger.error("Failed saving preset tiers: %s", exc, exc_info=True)
            safe_report(self, {"ERROR"}, f"Save failed: {exc}")
            return {"CANCELLED"}


class LOD_OT_apply_preset_tiers(Operator):
    """Apply preset tier definitions to the scene and recalculate transition distances."""

    bl_idname = "lod_tool.apply_preset_tiers"
    bl_label = "Apply to Scene"
    bl_description = "Applies preset tier definitions to the scene and updates switch distances"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        return bpy.ops.lod_tool.analyze_and_configure()


class LOD_OT_capture_scene_tiers(Operator):
    """Capture current active scene LOD tiers into the preset tier template."""

    bl_idname = "lod_tool.capture_scene_tiers"
    bl_label = "Capture Scene Tiers"
    bl_description = "Captures the active scene LOD tiers into the preset template"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        if not props.lods:
            safe_report(self, {"WARNING"}, "No active scene LOD tiers to capture.")
            return {"CANCELLED"}

        props.lod_preset_active_tiers.clear()
        for tier in props.lods:
            item = props.lod_preset_active_tiers.add()
            item.name = tier.name
            item.screen_size_pct = tier.screen_size_pct
            item.target_tris_pct = tier.target_tris_pct
            item.target_tris = tier.target_tris

        props.lod_preset_is_dirty = True
        safe_report(self, {"INFO"}, f"Captured {len(props.lods)} tiers from scene.")
        return {"FINISHED"}


LOD_OPERATOR_CLASSES = (
    LOD_OT_reset_to_preset,
    LOD_OT_analyze_and_configure,
    LOD_OT_generate_all,
    LOD_OT_solo_tier,
    LOD_OT_add_lod_tier,
    LOD_OT_remove_lod_tier,
    LOD_OT_preview_tier,
    LOD_OT_sync_selection_settings,
    LOD_OT_select_master_asset,
    LOD_OT_add_preset_tier,
    LOD_OT_remove_preset_tier,
    LOD_OT_save_preset_tiers,
    LOD_OT_apply_preset_tiers,
    LOD_OT_capture_scene_tiers,
)
