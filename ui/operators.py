"""
Master Pipeline Operators for OmniMesh LOD Analysis, Generation, Collision, Mesh Cleanup, Material Cleanup, Impostors, and Viewport Preview.
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
    from ..core.collision import CollisionManager
    from ..core.decimator import MeshDecimator
    from ..core.hierarchy import MeshMergeEngine
    from ..core.impostor import ImpostorManager
    from ..core.materials import MaterialOptimizer
    from ..core.metrics import (
        compute_bounding_sphere,
        compute_coupled_tolerances,
        compute_distance_from_screen_size,
        compute_vertical_fov,
        generate_logarithmic_screen_tiers,
    )
    from ..core.occlusion import HardenedOcclusionCuller
    from ..core.rigging import KinematicBonePruner, WeightSanitizer
    from ..core.sanitizer import MeshSanitizer
except (ImportError, ValueError):
    from core.collision import CollisionManager
    from core.decimator import MeshDecimator
    from core.hierarchy import MeshMergeEngine
    from core.impostor import ImpostorManager
    from core.materials import MaterialOptimizer
    from core.metrics import (
        compute_bounding_sphere,
        compute_coupled_tolerances,
        compute_distance_from_screen_size,
        compute_vertical_fov,
        generate_logarithmic_screen_tiers,
    )
    from core.occlusion import HardenedOcclusionCuller
    from core.rigging import KinematicBonePruner, WeightSanitizer
    from core.sanitizer import MeshSanitizer


def is_object_valid(obj: Any) -> bool:
    """Safely verify object RNA validity against bpy.data.objects."""
    if obj is None:
        return False
    if bpy is None:
        return True
    try:
        return obj.name in bpy.data.objects and getattr(obj, "data", None) is not None
    except (ReferenceError, AttributeError):
        return False


def get_selected_mesh_objects(context: Any) -> list[Any]:
    """Retrieves all selected mesh objects, or falls back to active object."""
    if not context:
        return []
    selected = [obj for obj in getattr(context, "selected_objects", []) if getattr(obj, "type", "") == "MESH"]
    if not selected and getattr(context, "active_object", None) and context.active_object.type == "MESH":
        selected = [context.active_object]
    return selected


def get_associated_armature(mesh_objs: list[Any]) -> Any:
    """Finds the shared armature modifier or parent across selected meshes."""
    for obj in mesh_objs:
        if obj.parent and getattr(obj.parent, "type", "") == "ARMATURE":
            return obj.parent
        for mod in getattr(obj, "modifiers", []):
            if getattr(mod, "type", "") == "ARMATURE" and getattr(mod, "object", None):
                return mod.object
    return None


def resolve_lod_context(context: Any) -> tuple[Any, Any, Any, bool]:
    """
    Robust Context Resolver:
    Returns: (scene_props, obj_props, master_object, is_derivative)

    Guarantees:
    1. Returns valid Scene-level Project Settings.
    2. If active object is a generated sub-LOD (e.g. Tree_LOD2), resolves upward to the Master LOD0.
    3. Handles name changes via native PointerProperty references with fallback to suffix parsing.
    4. Never triggers recursive decimation on derivative objects.
    """
    if not context or not hasattr(context, "scene") or not context.scene:
        return None, None, None, False

    scene_props = getattr(context.scene, "lod_tool", None)
    active_obj = getattr(context, "active_object", None)

    if not active_obj or getattr(active_obj, "type", "") != "MESH":
        return scene_props, scene_props, active_obj, False

    obj_props = getattr(active_obj, "lod_tool", None)
    if not obj_props:
        return scene_props, scene_props, active_obj, False

    # Check 1: Explicit pointer to root master
    if obj_props.is_generated_lod and obj_props.lod_root_object and is_object_valid(obj_props.lod_root_object):
        master_obj = obj_props.lod_root_object
        master_props = getattr(master_obj, "lod_tool", obj_props)
        return scene_props, master_props, master_obj, True

    # Check 2: Name pattern fallback if unlinked or imported (_LOD1.._LOD7 or _Impostor)
    name = active_obj.name
    if "_LOD" in name:
        base_name, _, suffix = name.rpartition("_LOD")
        if (suffix.isdigit() and int(suffix) > 0) or suffix.lower().startswith("_impostor") or suffix == "_Impostor":
            if bpy:
                root_obj = bpy.data.objects.get(base_name) or bpy.data.objects.get(f"{base_name}_LOD0")
                if root_obj and root_obj != active_obj:
                    root_props = getattr(root_obj, "lod_tool", obj_props)
                    return scene_props, root_props, root_obj, True

    # Active object is the true Master LOD0
    return scene_props, obj_props, active_obj, False


class LOD_OT_analyze_and_configure(Operator):
    """Analyze selected mesh bounding metrics and auto-populate recommended LOD screen tiers."""

    bl_idname = "lod_tool.analyze_and_configure"
    bl_label = "Auto-Configure LOD Tiers"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        all_coords = []
        for obj in mesh_objs:
            all_coords.extend([obj.matrix_world @ v.co for v in obj.data.vertices])

        if not all_coords:
            self.report({"WARNING"}, "Selected mesh contains zero vertices.")
            return {"CANCELLED"}

        center, radius = compute_bounding_sphere(all_coords)
        scene_props, obj_props, master_obj, _ = resolve_lod_context(context)
        props = obj_props or scene_props

        render = context.scene.render
        cam = context.scene.camera
        cam_angle = cam.data.angle if cam and cam.type == "CAMERA" else math.radians(60.0)
        sensor_fit = cam.data.sensor_fit if cam and cam.type == "CAMERA" else "AUTO"
        aspect_ratio = render.resolution_x / max(1, render.resolution_y)
        fov_v = compute_vertical_fov(cam_angle, aspect_ratio, sensor_fit)

        screen_tiers = generate_logarithmic_screen_tiers(
            k_tiers=props.lod_count,
            category=props.asset_category,
            progression_mode=props.progression_mode,
        )

        total_tris = sum(len(obj.data.polygons) for obj in mesh_objs)

        target_props_list = [props]
        if scene_props and scene_props != props:
            target_props_list.append(scene_props)

        for p in target_props_list:
            p.lods.clear()
            for i, s_pct in enumerate(screen_tiers):
                item = p.lods.add()
                item.name = f"LOD{i}"
                item.level_index = i
                item.screen_size_pct = s_pct

                s_frac = max(0.001, s_pct / 100.0)
                item.distance_m = compute_distance_from_screen_size(radius, s_frac, fov_v)

                qem_ratio = max(0.01, min(1.0, math.pow(s_frac, 1.5)))
                item.triangle_target = max(12, int(round(total_tris * qem_ratio)))
                item.actual_triangles = total_tris if i == 0 else 0
                item.reduction_pct = 0.0 if i == 0 else (1.0 - qem_ratio) * 100.0
                item.mat_slots_count = len(mesh_objs[0].material_slots) if mesh_objs else 0

        first_name = mesh_objs[0].name.split("_LOD")[0]
        if not props.export_base_name:
            props.export_base_name = first_name
        if scene_props and not scene_props.export_base_name:
            scene_props.export_base_name = first_name

        props.is_configured = True
        self.report(
            {"INFO"},
            f"Configured {len(screen_tiers)} LODs for '{first_name}' (Radius: {radius:.2f}m, Base: {total_tris:,} tris).",
        )
        return {"FINISHED"}


class LOD_OT_sync_selection_settings(Operator):
    """Apply the active master mesh's LOD settings across all selected mesh objects."""

    bl_idname = "lod_tool.sync_selection_settings"
    bl_label = "Copy LOD Settings to Selected"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        _, src_props, master_obj, _ = resolve_lod_context(context)
        if not master_obj or not src_props:
            self.report({"WARNING"}, "No valid active master mesh object.")
            return {"CANCELLED"}

        selected_meshes = [
            obj
            for obj in get_selected_mesh_objects(context)
            if obj != master_obj and not getattr(getattr(obj, "lod_tool", None), "is_generated_lod", False)
        ]

        if not selected_meshes:
            self.report({"INFO"}, "No additional unconfigured meshes in selection.")
            return {"FINISHED"}

        for target in selected_meshes:
            dst_props = target.lod_tool
            dst_props.asset_category = src_props.asset_category
            dst_props.progression_mode = src_props.progression_mode
            dst_props.lod_count = src_props.lod_count
            dst_props.tau_sse = src_props.tau_sse
            dst_props.preserve_silhouette = src_props.preserve_silhouette
            dst_props.pin_uv_seams = src_props.pin_uv_seams
            dst_props.pin_material_borders = src_props.pin_material_borders
            dst_props.enable_occlusion_culling = src_props.enable_occlusion_culling
            dst_props.impostor_mode = src_props.impostor_mode
            dst_props.collision_hull_count = src_props.collision_hull_count
            dst_props.is_configured = True

        self.report({"INFO"}, f"Synchronized LOD settings to {len(selected_meshes)} selected mesh objects.")
        return {"FINISHED"}


class LOD_OT_select_master_asset(Operator):
    """Select and activate the root master asset for the active sub-LOD derivative."""

    bl_idname = "lod_tool.select_master_asset"
    bl_label = "Select Root Master Asset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        _, _, master_obj, _ = resolve_lod_context(context)
        if not master_obj:
            self.report({"WARNING"}, "No master asset found.")
            return {"CANCELLED"}

        bpy.ops.object.select_all(action="DESELECT")
        try:
            master_obj.hide_set(False, view_layer=context.view_layer)
            master_obj.hide_viewport = False
        except (RuntimeError, AttributeError):
            pass

        master_obj.select_set(True)
        context.view_layer.objects.active = master_obj
        self.report({"INFO"}, f"Selected root master asset: '{master_obj.name}'")
        return {"FINISHED"}


class LOD_OT_clean_and_repair_mesh(Operator):
    """Execute 3-tier mesh sanitization, geometry hygiene, non-manifold repair, and hole sealing."""

    bl_idname = "lod_tool.clean_and_repair_mesh"
    bl_label = "Clean & Repair Selected Meshes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        _, obj_props, _, _ = resolve_lod_context(context)
        props = obj_props or context.scene.lod_tool

        total_zero_faces = 0
        total_zero_edges = 0
        total_wire_edges = 0
        total_loose_verts = 0
        total_duplicate_faces = 0
        total_welded_verts = 0
        total_split_bowties = 0
        total_filled_holes = 0
        total_culled_islands = 0

        for obj in mesh_objs:
            bm = bmesh.new()
            bm.from_mesh(obj.data)

            stats = MeshSanitizer.sanitize_mesh_full(
                bm,
                enable_weld=props.cleanup_enable_weld,
                epsilon_merge=props.cleanup_weld_distance,
                enable_split_non_manifold=props.cleanup_enable_split_non_manifold,
                enable_fill_holes=props.cleanup_enable_fill_holes,
                hole_max_edges=props.cleanup_hole_max_edges,
                enable_triangulate_ngons=props.cleanup_enable_triangulate_ngons,
                enable_cull_micro_islands=props.cleanup_enable_cull_micro_islands,
                w_crit=props.cleanup_island_size_threshold,
                normal_recalc_policy=props.cleanup_normal_policy,
                world_matrix=obj.matrix_world,
            )

            bm.to_mesh(obj.data)
            bm.free()
            obj.data.update()

            total_zero_faces += stats.get("zero_faces", 0)
            total_zero_edges += stats.get("zero_edges", 0)
            total_wire_edges += stats.get("wire_edges", 0)
            total_loose_verts += stats.get("loose_verts", 0)
            total_duplicate_faces += stats.get("duplicate_faces", 0)
            total_welded_verts += stats.get("welded_verts", 0)
            total_split_bowties += stats.get("split_bowties", 0)
            total_filled_holes += stats.get("filled_holes", 0)
            total_culled_islands += stats.get("culled_islands", 0)

        summary_msg = (
            f"Cleaned: {total_loose_verts} loose verts, {total_wire_edges} wire edges, "
            f"{total_zero_faces} zero faces, {total_duplicate_faces} dup faces. "
            f"Repaired: {total_welded_verts} welded, {total_split_bowties} bowties, {total_filled_holes} holes."
        )
        props.last_cleanup_summary = summary_msg
        self.report({"INFO"}, f"✔ {summary_msg}")
        return {"FINISHED"}


class LOD_OT_clean_and_repair_materials(Operator):
    """Execute material slot compaction, deduplication, AST hash merging, and micro-material consolidation."""

    bl_idname = "lod_tool.clean_and_repair_materials"
    bl_label = "Clean & Consolidate Materials"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        _, obj_props, _, _ = resolve_lod_context(context)
        props = obj_props or context.scene.lod_tool

        stats = MaterialOptimizer.clean_materials_full(
            mesh_objs=mesh_objs,
            purge_unused_slots=props.mat_cleanup_purge_unused_slots,
            deduplicate_slots=props.mat_cleanup_deduplicate_slots,
            merge_duplicate_datablocks=props.mat_cleanup_merge_duplicate_datablocks,
            remove_orphan_nodes=props.mat_cleanup_remove_orphan_nodes,
            enable_micro_consolidation=props.mat_cleanup_enable_micro_consolidation,
            micro_area_pct=props.mat_cleanup_micro_area_pct,
            repair_missing_textures=props.mat_cleanup_repair_missing_textures,
            purge_orphans_blendfile=props.mat_cleanup_purge_orphans_blendfile,
        )

        summary_msg = (
            f"Removed {stats['slots_removed']} unused/dup slots ({stats['faces_remapped']} faces remapped), "
            f"merged {stats['merged_datablocks']} duplicate materials, "
            f"cleaned {stats['orphan_nodes_removed']} dead nodes."
        )
        if stats["consolidated_slots"] > 0:
            summary_msg += f" Consolidated {stats['consolidated_slots']} micro-materials."
        if stats["repaired_textures"] > 0:
            summary_msg += f" Repaired {stats['repaired_textures']} missing textures."
        if stats["purged_orphans"] > 0:
            summary_msg += f" Purged {stats['purged_orphans']} orphan materials."

        props.last_material_cleanup_summary = summary_msg
        self.report({"INFO"}, f"✔ {summary_msg}")
        return {"FINISHED"}


class LOD_OT_generate_all(Operator):
    """Execute complete multi-LOD simplification, occlusion culling, rigging preservation, and normal reprojection."""

    bl_idname = "lod_tool.generate_all"
    bl_label = "Generate All LODs"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        scene_props, obj_props, master_obj, _ = resolve_lod_context(context)
        props = obj_props or scene_props

        if not props.lods:
            self.report({"ERROR"}, "No LOD tiers configured. Run Auto-Configure first.")
            return {"CANCELLED"}

        armature_obj = get_associated_armature(mesh_objs)
        orig_pose_pos = None
        if armature_obj and hasattr(armature_obj.data, "pose_position"):
            orig_pose_pos = armature_obj.data.pose_position
            armature_obj.data.pose_position = "REST"

        total_culled_faces = 0
        total_culled_islands = 0

        try:
            base_name = props.export_base_name or mesh_objs[0].name.split("_LOD")[0]
            coll_name = f"{base_name}_LODs"
            target_coll = bpy.data.collections.get(coll_name)
            if not target_coll:
                target_coll = bpy.data.collections.new(coll_name)
                context.scene.collection.children.link(target_coll)

            for obj in mesh_objs:
                if not obj.parent or obj.parent.type != "ARMATURE":
                    bpy.context.view_layer.objects.active = obj
                    obj.select_set(True)
                    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

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
            generated_tier_objects = []

            for i, tier in enumerate(props.lods):
                s_frac = tier.screen_size_pct / 100.0
                tolerances = compute_coupled_tolerances(radius, s_frac, 1.5, render.resolution_y)
                should_merge = props.hierarchy_mode == "MERGE_DISTANT" and i >= props.merge_lod_start

                if should_merge and len(mesh_objs) > 1:
                    merged_name = f"{base_name}_LOD{i}"
                    existing = bpy.data.objects.get(merged_name)
                    if existing and existing not in mesh_objs:
                        bpy.data.objects.remove(existing, do_unlink=True)

                    tier_obj = MeshMergeEngine.consolidate_and_merge_meshes(mesh_objs, merged_name, armature_obj)
                    tier_obj.lod_tool.is_generated_lod = True
                    tier_obj.lod_tool.lod_root_object = mesh_objs[0]
                    tier_obj.lod_tool.lod_index = i
                    target_coll.objects.link(tier_obj)

                    bm = bmesh.new()
                    bm.from_mesh(tier_obj.data)
                    MeshSanitizer.sanitize_mesh_full(bm, tolerances["epsilon_merge"], tolerances["w_crit"])

                    # Occlusion & Interior Geometry Culling
                    if props.enable_occlusion_culling and i >= props.occlusion_lod_start:
                        cull_res = HardenedOcclusionCuller.cull_interior_faces(
                            tier_obj,
                            bm,
                            ray_density=props.occlusion_ray_density,
                            evaluate_alpha=props.occlusion_evaluate_alpha,
                            delta_world=tolerances["delta_world"],
                        )
                        total_culled_faces += cull_res.get("culled_faces", 0)
                        total_culled_islands += cull_res.get("culled_islands", 0)

                    pinned_verts = MeshDecimator.tag_boundaries_and_uv_seams(bm)
                    MeshDecimator.apply_planar_limited_dissolve(bm, math.radians(tolerances["planar_angle_deg"]))
                    MeshDecimator.inject_curvature_weights(tier_obj, bm, pinned_verts)
                    bm.to_mesh(tier_obj.data)
                    bm.free()
                    tier_obj.data.update()

                    MeshDecimator.execute_decimate_qem(tier_obj, tolerances["qem_ratio"], use_curvature_weight=True)

                    if props.purge_distant_shape_keys and i >= 2:
                        MeshDecimator.prepare_and_clean_shape_keys(tier_obj, purge=True)

                    if armature_obj and len(tier_obj.vertex_groups) > 0:
                        if props.enable_leaf_bone_pruning and i >= props.leaf_bone_lod_start:
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
                    tier.mat_slots_count = len(tier_obj.material_slots)
                    tier.generated_obj = tier_obj
                    generated_tier_objects.append(tier_obj)

                else:
                    tier_sub_objs = []
                    for src_obj in mesh_objs:
                        src_base = src_obj.name.split("_LOD")[0]
                        tier_name = f"{src_base}_LOD{i}"

                        existing = bpy.data.objects.get(tier_name)
                        if existing and existing != src_obj:
                            bpy.data.objects.remove(existing, do_unlink=True)

                        if i == 0 and src_obj.name == tier_name:
                            tier_obj = src_obj
                        else:
                            tier_mesh = src_obj.data.copy()
                            tier_mesh.name = f"{tier_name}_Mesh"
                            tier_obj = src_obj.copy()
                            tier_obj.name = tier_name
                            tier_obj.data = tier_mesh

                            tier_obj.lod_tool.is_generated_lod = True
                            tier_obj.lod_tool.lod_root_object = src_obj
                            tier_obj.lod_tool.lod_index = i

                            if src_obj.parent:
                                tier_obj.parent = src_obj.parent
                                tier_obj.parent_type = src_obj.parent_type
                                if hasattr(src_obj, "parent_bone") and src_obj.parent_bone:
                                    tier_obj.parent_bone = src_obj.parent_bone
                                tier_obj.matrix_parent_inverse = src_obj.matrix_parent_inverse.copy()

                            if tier_obj.name not in target_coll.objects:
                                target_coll.objects.link(tier_obj)

                        if i > 0:
                            bm = bmesh.new()
                            bm.from_mesh(tier_obj.data)

                            if props.auto_sanitize_before_lod:
                                MeshSanitizer.execute_tier0_pure_hygiene(bm)

                            if props.enable_occlusion_culling and i >= props.occlusion_lod_start:
                                cull_res = HardenedOcclusionCuller.cull_interior_faces(
                                    tier_obj,
                                    bm,
                                    ray_density=props.occlusion_ray_density,
                                    evaluate_alpha=props.occlusion_evaluate_alpha,
                                    delta_world=tolerances["delta_world"],
                                )
                                total_culled_faces += cull_res.get("culled_faces", 0)
                                total_culled_islands += cull_res.get("culled_islands", 0)

                            pinned_verts = MeshDecimator.tag_boundaries_and_uv_seams(bm)
                            MeshDecimator.apply_planar_limited_dissolve(
                                bm, math.radians(tolerances["planar_angle_deg"])
                            )
                            MeshDecimator.inject_curvature_weights(tier_obj, bm, pinned_verts)
                            bm.to_mesh(tier_obj.data)
                            bm.free()
                            tier_obj.data.update()

                            MeshDecimator.execute_decimate_qem(
                                tier_obj, tolerances["qem_ratio"], use_curvature_weight=True
                            )

                            if props.purge_distant_shape_keys and i >= 2:
                                MeshDecimator.prepare_and_clean_shape_keys(tier_obj, purge=True)

                            if armature_obj and len(tier_obj.vertex_groups) > 0:
                                if props.enable_leaf_bone_pruning and i >= props.leaf_bone_lod_start:
                                    KinematicBonePruner.prune_kinematic_subtrees(
                                        tier_obj,
                                        armature_obj,
                                        screen_distance_m=tier.distance_m,
                                        fov_v_rad=fov_v,
                                        resolution_y=render.resolution_y,
                                        pixel_threshold=1.5,
                                    )
                                WeightSanitizer.normalize_and_clamp_weights(tier_obj, max_influences=max_influences)

                        tier_sub_objs.append(tier_obj)

                    tier.actual_tris = sum(len(o.data.polygons) for o in tier_sub_objs)
                    tier.mat_slots_count = sum(len(o.material_slots) for o in tier_sub_objs)
                    tier.generated_obj = tier_sub_objs[0]
                    generated_tier_objects.extend(tier_sub_objs)

            base_tris = props.lods[0].actual_tris
            final_tris = props.lods[-1].actual_tris
            red_pct = ((base_tris - final_tris) / max(1, base_tris)) * 100.0 if base_tris > 0 else 0.0

            props.last_generated_base_tris = base_tris
            props.last_generated_final_tris = final_tris
            props.last_generated_reduction_pct = red_pct
            props.last_generated_tier_count = len(props.lods)
            props.last_culled_faces_count = total_culled_faces
            props.last_culled_islands_count = total_culled_islands

            if scene_props and scene_props != props:
                scene_props.last_generated_base_tris = base_tris
                scene_props.last_generated_final_tris = final_tris
                scene_props.last_generated_reduction_pct = red_pct
                scene_props.last_generated_tier_count = len(props.lods)
                scene_props.last_culled_faces_count = total_culled_faces
                scene_props.last_culled_islands_count = total_culled_islands

            self.report(
                {"INFO"},
                f"Successfully generated {len(props.lods)} LOD tiers: {base_tris:,} -> {final_tris:,} tris (-{red_pct:.1f}% reduction).",
            )
            return {"FINISHED"}
        finally:
            if armature_obj and orig_pose_pos:
                armature_obj.data.pose_position = orig_pose_pos


class LOD_OT_generate_impostor(Operator):
    """Generate 8-way Cross-Quad or Octahedral Billboard Impostor for selected meshes."""

    bl_idname = "lod_tool.generate_impostor"
    bl_label = "Generate Impostor Billboard"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        scene_props, obj_props, _, _ = resolve_lod_context(context)
        props = obj_props or scene_props
        target_engine = scene_props.target_engine if scene_props else props.target_engine
        base_name = props.export_base_name or mesh_objs[0].name.split("_LOD")[0]

        impostor_obj = ImpostorManager.generate_impostor_for_objects(
            mesh_objs=mesh_objs,
            base_name=base_name,
            mode=props.impostor_mode,
            target_engine=target_engine,
        )

        if not impostor_obj:
            self.report({"ERROR"}, "Failed to generate impostor geometry.")
            return {"CANCELLED"}

        impostor_obj.lod_tool.is_generated_lod = True
        impostor_obj.lod_tool.lod_root_object = mesh_objs[0]

        if props.impostor_replace_last_lod and props.lods:
            last_tier = props.lods[-1]
            last_tier.generated_obj = impostor_obj
            last_tier.actual_triangles = len(impostor_obj.data.polygons)

        tris_count = len(impostor_obj.data.polygons)
        status_msg = f"Generated {props.impostor_mode} Impostor ({tris_count} tris) for '{base_name}'."
        props.last_impostor_status = status_msg
        self.report({"INFO"}, f"✔ {status_msg}")
        return {"FINISHED"}


class LOD_OT_remove_impostor(Operator):
    """Remove and purge generated Impostor billboard object."""

    bl_idname = "lod_tool.remove_impostor"
    bl_label = "Remove Impostor"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        mesh_objs = get_selected_mesh_objects(context)
        _, obj_props, _, _ = resolve_lod_context(context)
        props = obj_props or context.scene.lod_tool
        base_name = props.export_base_name or (mesh_objs[0].name.split("_LOD")[0] if mesh_objs else "")

        impostor_name = f"{base_name}_LOD_Impostor"
        existing = bpy.data.objects.get(impostor_name)
        if existing:
            bpy.data.objects.remove(existing, do_unlink=True)
            props.last_impostor_status = ""
            self.report({"INFO"}, f"Removed Impostor object '{impostor_name}'.")
            return {"FINISHED"}

        self.report({"WARNING"}, f"No Impostor found named '{impostor_name}'.")
        return {"CANCELLED"}


class LOD_OT_generate_collision_hulls(Operator):
    """Generate multi-convex collision hulls in Blender viewport for the selected mesh objects."""

    bl_idname = "lod_tool.generate_collision_hulls"
    bl_label = "Generate Collision Hulls"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        _, obj_props, _, _ = resolve_lod_context(context)
        props = obj_props or context.scene.lod_tool
        base_name = props.export_base_name or mesh_objs[0].name.split("_LOD")[0]

        colliders = CollisionManager.generate_colliders_for_objects(
            mesh_objs=mesh_objs,
            base_name=base_name,
            hull_count=props.collision_hull_count,
            max_verts_per_hull=props.collision_max_verts_per_hull,
            concavity_threshold=props.collision_concavity_threshold,
            mode=props.collision_decomposition_mode,
        )

        props.last_generated_collider_count = len(colliders)
        self.report(
            {"INFO"},
            f"Generated {len(colliders)} convex collision hulls in collection '{base_name}_Colliders'.",
        )
        return {"FINISHED"}


class LOD_OT_remove_collision_hulls(Operator):
    """Remove and purge all generated collision hulls for selected assets."""

    bl_idname = "lod_tool.remove_collision_hulls"
    bl_label = "Remove Collision Hulls"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        mesh_objs = get_selected_mesh_objects(context)
        _, obj_props, _, _ = resolve_lod_context(context)
        props = obj_props or context.scene.lod_tool
        base_name = props.export_base_name or (mesh_objs[0].name.split("_LOD")[0] if mesh_objs else "")

        removed = CollisionManager.remove_colliders_for_objects(mesh_objs, base_name)
        props.last_generated_collider_count = 0
        self.report({"INFO"}, f"Removed {removed} collision hull objects.")
        return {"FINISHED"}


class LOD_OT_preview_tier(Operator):
    """Isolate and preview a single LOD tier in the 3D viewport."""

    bl_idname = "lod_tool.preview_tier"
    bl_label = "Preview Tier"
    bl_options = {"REGISTER"}

    tier_index: bpy.props.IntProperty(name="Tier Index", default=0)  # type: ignore

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        _, obj_props, _, _ = resolve_lod_context(context)
        props = obj_props or context.scene.lod_tool
        props.active_lod_index = self.tier_index

        base_name = props.export_base_name
        coll = bpy.data.collections.get(f"{base_name}_LODs")

        if coll:
            for obj in coll.objects:
                if getattr(obj, "type", "") == "MESH":
                    is_target = f"_LOD{self.tier_index}" in obj.name
                    obj.hide_viewport = not is_target
                    obj.hide_set(not is_target, view_layer=context.view_layer)
        elif props.lods:
            for i, tier in enumerate(props.lods):
                if tier.generated_obj and is_object_valid(tier.generated_obj):
                    is_target = i == self.tier_index
                    tier.generated_obj.hide_viewport = not is_target

        self.report({"INFO"}, f"Isolated Viewport Preview: LOD{self.tier_index}")
        return {"FINISHED"}


class LOD_OT_toggle_simulator(Operator):
    """Toggle real-time distance-based LOD simulator."""

    bl_idname = "lod_tool.toggle_simulator"
    bl_label = "Toggle Real-Time Simulator"
    bl_options = {"REGISTER"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        props = context.scene.lod_tool

        try:
            from ..core.simulator import RealTimeLODSimulator
        except (ImportError, ValueError):
            from core.simulator import RealTimeLODSimulator

        if props.is_simulator_active:
            RealTimeLODSimulator.stop()
            props.is_simulator_active = False
            self.report({"INFO"}, "Real-Time LOD Simulator stopped.")
        else:
            started = RealTimeLODSimulator.start(context)
            if started:
                props.is_simulator_active = True
                self.report({"INFO"}, "Real-Time LOD Simulator active.")
            else:
                self.report({"WARNING"}, "Failed to start simulator. Ensure LODs are generated.")
        return {"FINISHED"}


class LOD_OT_toggle_split_preview(Operator):
    """Toggle interactive A/B split-screen viewport preview."""

    bl_idname = "lod_tool.toggle_split_preview"
    bl_label = "Toggle Split Preview"
    bl_options = {"REGISTER"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        props = context.scene.lod_tool

        try:
            from .hud import ViewportSplitPreview
        except (ImportError, ValueError):
            from ui.hud import ViewportSplitPreview

        if props.is_split_active:
            ViewportSplitPreview.stop()
            props.is_split_active = False
            self.report({"INFO"}, "Split-screen preview disabled.")
        else:
            started = ViewportSplitPreview.start(context)
            if started:
                props.is_split_active = True
                self.report({"INFO"}, "Split-screen A/B preview enabled.")
            else:
                self.report({"WARNING"}, "Split-screen preview requires generated LODs.")
        return {"FINISHED"}


# Registration Order
OPERATOR_CLASSES = (
    LOD_OT_analyze_and_configure,
    LOD_OT_sync_selection_settings,
    LOD_OT_select_master_asset,
    LOD_OT_clean_and_repair_mesh,
    LOD_OT_clean_and_repair_materials,
    LOD_OT_generate_all,
    LOD_OT_generate_impostor,
    LOD_OT_remove_impostor,
    LOD_OT_generate_collision_hulls,
    LOD_OT_remove_collision_hulls,
    LOD_OT_preview_tier,
    LOD_OT_toggle_simulator,
    LOD_OT_toggle_split_preview,
)


def register_operators() -> None:
    if not bpy:
        return
    for cls in OPERATOR_CLASSES:
        bpy.utils.register_class(cls)


def unregister_operators() -> None:
    if not bpy:
        return
    for cls in reversed(OPERATOR_CLASSES):
        bpy.utils.unregister_class(cls)
