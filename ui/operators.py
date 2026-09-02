"""
User Operators for LOD-Tool.
Implements the 7-step generation loop, interactive previews, HUD overlays,
real-time distance simulation, and engine export execution.
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
    from core.collision import CollisionManager
    from core.decimator import MeshDecimator
    from core.hierarchy import CollectionCloneDAG, LayerCollectionGuard, MeshMergeEngine
    from core.impostor import ImpostorManager
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
    from core.pbr_importer import BatchMaterialSlotMatcher, ShaderGraphBuilder
    from core.pivot import PivotPreservationEngine
    from core.rigging import KinematicBonePruner, WeightSanitizer
    from core.sanitizer import MeshSanitizer
    from core.slender import SlenderFeatureCuller
except (ImportError, ValueError):
    from ..core.collision import CollisionManager
    from ..core.decimator import MeshDecimator
    from ..core.hierarchy import CollectionCloneDAG, LayerCollectionGuard, MeshMergeEngine
    from ..core.impostor import ImpostorManager
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
    from ..core.pbr_importer import BatchMaterialSlotMatcher, ShaderGraphBuilder
    from ..core.pivot import PivotPreservationEngine
    from ..core.rigging import KinematicBonePruner, WeightSanitizer
    from ..core.sanitizer import MeshSanitizer
    from ..core.slender import SlenderFeatureCuller


def is_object_valid(obj: Any) -> bool:
    """Safely check if a Blender object exists and is not freed/invalidated."""
    if obj is None:
        return False
    try:
        _ = getattr(obj, "name", None)
        return True
    except (ReferenceError, AttributeError):
        return False


def get_selected_mesh_objects(context: Any) -> list[Any]:
    """Retrieve all valid, non-collider, non-impostor MESH objects from selection or active object."""
    if not context:
        return []
    objs = context.selected_objects if hasattr(context, "selected_objects") else []
    if not objs and context.active_object:
        objs = [context.active_object]

    raw_meshes = []
    for obj in objs:
        if not is_object_valid(obj):
            continue
        if getattr(obj, "type", "") == "MESH":
            name = getattr(obj, "name", "")
            is_col = bool(getattr(obj, "get", lambda *_: False)("_is_collider", False) is True)
            if not is_col and not name.startswith("UCX_"):
                raw_meshes.append(obj)

    base_meshes = [obj for obj in raw_meshes if not any(f"_LOD{n}" in getattr(obj, "name", "") for n in range(1, 11))]
    return base_meshes if base_meshes else raw_meshes


def get_associated_armature(mesh_objs: list[Any]) -> Any:
    """Find armature parent or modifier attached to any of the provided mesh objects."""
    for obj in mesh_objs:
        if not is_object_valid(obj):
            continue
        if (
            getattr(obj, "parent", None)
            and is_object_valid(obj.parent)
            and getattr(obj.parent, "type", "") == "ARMATURE"
        ):
            return obj.parent
        for mod in getattr(obj, "modifiers", []):
            if getattr(mod, "type", "") == "ARMATURE" and is_object_valid(getattr(mod, "object", None)):
                return mod.object
    return None


def resolve_lod_context(context: Any) -> tuple[Any, Any | None, bool]:
    """
    Context Resolver: returns (active_settings, master_object_or_coll, is_derivative_lod).
    """
    if not context:
        return None, None, False

    scene_props = getattr(getattr(context, "scene", None), "lod_tool", None)
    active_obj = getattr(context, "active_object", None)

    if not active_obj or getattr(active_obj, "type", "") != "MESH":
        return scene_props, None, False

    obj_props = getattr(active_obj, "lod_tool", None)
    if not obj_props:
        return scene_props, active_obj, False

    if bool(getattr(obj_props, "is_generated_lod", False) is True):
        master_name = getattr(obj_props, "lod_root_object", "")
        master_obj = bpy.data.objects.get(master_name) if bpy and master_name else None
        if master_obj and hasattr(master_obj, "lod_tool"):
            return master_obj.lod_tool, master_obj, True
        return obj_props, active_obj, True

    is_cfg = bool(getattr(obj_props, "is_configured", False) is True)
    return (obj_props if is_cfg else scene_props), active_obj, False


class LOD_OT_inspect_lod0(Operator):
    """Preflight check: Inspect active mesh geometry for unapplied transforms, loose vertices, and non-manifold topology."""

    bl_idname = "lod_tool.inspect_lod0"
    bl_label = "Inspect LOD0"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and get_selected_mesh_objects(context))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props = context.scene.lod_tool
        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        total_loose_verts = 0
        total_degenerate_tris = 0
        has_unapplied_scale = False
        missing_mats = 0

        for obj in mesh_objs:
            s = obj.scale
            if abs(s.x - 1.0) > 1e-4 or abs(s.y - 1.0) > 1e-4 or abs(s.z - 1.0) > 1e-4:
                has_unapplied_scale = True

            if len(obj.material_slots) == 0 or any(slot.material is None for slot in obj.material_slots):
                missing_mats += 1

            bm = bmesh.new()
            try:
                bm.from_mesh(obj.data)
                for v in bm.verts:
                    if len(v.link_edges) == 0:
                        total_loose_verts += 1
                for f in bm.faces:
                    if f.calc_area() <= 1e-10:
                        total_degenerate_tris += 1
            finally:
                bm.free()

        props.preflight_inspected = True
        props.preflight_loose_verts = total_loose_verts
        props.preflight_degenerate_tris = total_degenerate_tris
        props.preflight_unapplied_scale = has_unapplied_scale
        props.preflight_missing_materials = missing_mats

        is_clean = (total_loose_verts == 0) and (total_degenerate_tris == 0) and (not has_unapplied_scale)
        props.preflight_is_clean = is_clean

        if is_clean:
            props.preflight_summary_text = f"✔ LOD0 Healthy ({len(mesh_objs)} mesh(es), All Transforms Applied)"
            self.report({"INFO"}, props.preflight_summary_text)
        else:
            issues = []
            if has_unapplied_scale:
                issues.append("Unapplied Scale")
            if total_loose_verts > 0:
                issues.append(f"{total_loose_verts} Loose Verts")
            if total_degenerate_tris > 0:
                issues.append(f"{total_degenerate_tris} Degenerates")
            if missing_mats > 0:
                issues.append(f"{missing_mats} Missing Mats")
            props.preflight_summary_text = f"⚠ Issues: {', '.join(issues)}"
            self.report({"WARNING"}, f"LOD0 Inspection: {', '.join(issues)}")

        return {"FINISHED"}


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
            self.report({"WARNING"}, "No mesh objects selected.")
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
            self.report({"WARNING"}, "Selected meshes contain no vertex coordinates.")
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
        self.report(
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
                and not context.collection.name.endswith(tuple(f"_LOD{n}" for n in range(1, 11)))
            ):
                src_coll = context.collection
            elif mesh_objs and getattr(mesh_objs[0], "users_collection", []):
                for c in mesh_objs[0].users_collection:
                    if not c.name.endswith(tuple(f"_LOD{n}" for n in range(1, 11))) and c != context.scene.collection:
                        src_coll = c
                        break

            if not src_coll:
                src_coll, root_pivot = CollectionCloneDAG.wrap_loose_objects_into_root_collection(mesh_objs, base_name)
            else:
                root_pivot, _, _, _ = PivotPreservationEngine.identify_pivots_and_sockets(src_coll)

            for obj in mesh_objs:
                if not obj.parent or getattr(obj.parent, "type", "") != "ARMATURE":
                    try:
                        bpy.context.view_layer.objects.active = obj
                        obj.select_set(True)
                        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
                    except Exception as exc:
                        logger.debug("Transform apply skipped for %s: %s", getattr(obj, "name", "obj"), exc)

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
                        # LOD0 is source collection
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
                                    if hasattr(tier_pivot, "matrix_world") and hasattr(
                                        tier_pivot.matrix_world, "inverted"
                                    ):
                                        try:
                                            lod_obj.matrix_parent_inverse = tier_pivot.matrix_world.inverted()
                                        except Exception as exc:
                                            logger.debug("Matrix inversion failed: %s", exc)

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

            # Compute summary metrics
            if len(props.lods) > 0:
                base_tris_val = props.lods[0].actual_tris or props.lods[0].target_tris or 1
                final_tris_val = props.lods[-1].actual_tris or props.lods[-1].target_tris or 1
                reduction_pct = max(0.0, (1.0 - final_tris_val / float(base_tris_val)) * 100.0)

                props.last_generated_base_tris = base_tris_val
                props.last_generated_final_tris = final_tris_val
                props.last_generated_reduction_pct = reduction_pct
                props.last_generated_tier_count = len(props.lods)

            self.report({"INFO"}, f"Successfully generated {len(props.lods)} Sibling LOD Collections for '{base_name}'")
            return {"FINISHED"}
        finally:
            if armature_obj and orig_pose_pos and hasattr(armature_obj.data, "pose_position"):
                armature_obj.data.pose_position = orig_pose_pos


class LOD_OT_generate_impostor(Operator):
    """Bake and construct Billboard or Octahedral Impostor asset as sibling collection {BaseName}_LOD_Impostor."""

    bl_idname = "lod_tool.generate_impostor"
    bl_label = "Generate Impostor Billboard"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and get_selected_mesh_objects(context))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        mesh_objs = get_selected_mesh_objects(context)
        base_name = props.export_base_name or (
            context.active_object.name if context.active_object else mesh_objs[0].name
        )
        base_name = base_name.split("_LOD")[0]

        target_coll_name = f"{base_name}_LOD_Impostor"

        res = ImpostorManager.generate_impostor_for_objects(
            mesh_objs,
            base_name,
            mode=props.impostor_mode,
            target_engine=getattr(props, "target_engine", "UE5"),
            target_collection_name=target_coll_name,
        )

        if not res:
            self.report({"ERROR"}, "Failed to generate impostor billboard.")
            return {"CANCELLED"}

        props.last_impostor_status = f"Generated {props.impostor_mode} in '{target_coll_name}'"
        self.report({"INFO"}, props.last_impostor_status)
        return {"FINISHED"}


class LOD_OT_remove_impostor(Operator):
    """Remove generated Impostor collection."""

    bl_idname = "lod_tool.remove_impostor"
    bl_label = "Remove Impostor"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context)

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        base_name = props.export_base_name or (context.active_object.name if context.active_object else "Asset")
        base_name = base_name.split("_LOD")[0]

        target_coll = bpy.data.collections.get(f"{base_name}_LOD_Impostor")
        if target_coll:
            for obj in list(target_coll.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.collections.remove(target_coll)
            props.last_impostor_status = "Removed impostor collection"
            self.report({"INFO"}, "Removed impostor collection.")
        return {"FINISHED"}


class LOD_OT_generate_collision_hulls(Operator):
    """Generate multi-convex collision decomposition hulls in sibling collection {BaseName}_Colliders."""

    bl_idname = "lod_tool.generate_collision_hulls"
    bl_label = "Generate Collision Hulls"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and get_selected_mesh_objects(context))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        mesh_objs = get_selected_mesh_objects(context)
        base_name = props.export_base_name or (
            context.active_object.name if context.active_object else mesh_objs[0].name
        )
        base_name = base_name.split("_LOD")[0]

        created_hulls = CollisionManager.generate_colliders_for_objects(
            mesh_objs,
            base_name,
            mode=props.collision_decomposition_mode,
            hull_count=props.collision_hull_count,
            max_verts_per_hull=props.collision_max_verts_per_hull,
            concavity_threshold=props.collision_concavity_threshold,
            target_collection_name=f"{base_name}_Colliders",
        )

        props.last_generated_collider_count = len(created_hulls)
        self.report({"INFO"}, f"Generated {len(created_hulls)} collision hulls in '{base_name}_Colliders'")
        return {"FINISHED"}


class LOD_OT_remove_collision_hulls(Operator):
    """Remove generated collision hulls from scene."""

    bl_idname = "lod_tool.remove_collision_hulls"
    bl_label = "Remove Colliders"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        mesh_objs = get_selected_mesh_objects(context)
        base_name = props.export_base_name or (context.active_object.name if context.active_object else "Asset")
        base_name = base_name.split("_LOD")[0]

        removed = CollisionManager.remove_colliders_for_objects(mesh_objs, base_name)
        props.last_generated_collider_count = 0
        self.report({"INFO"}, f"Removed {removed} collision hulls.")
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
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        target_idx = int(self.tier_index)
        props.active_lod_index = target_idx

        base_name = props.export_base_name or (context.active_object.name if context.active_object else "Asset")
        base_name = base_name.split("_LOD")[0]

        # Sibling collection visibility switching
        for i in range(len(props.lods)):
            c_name = f"{base_name}_LOD{i}" if i > 0 else base_name
            coll = bpy.data.collections.get(c_name)
            if coll:
                coll.hide_viewport = i != target_idx

        self.report({"INFO"}, f"Previewing LOD Tier: LOD{target_idx}")
        return {"FINISHED"}


class LOD_OT_toggle_simulator(Operator):
    """Toggle live real-time camera distance viewport simulation."""

    bl_idname = "lod_tool.toggle_simulator"
    bl_label = "Toggle Simulation"
    bl_options = {"REGISTER"}

    def execute(self, context: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        from .simulator_ops import OmniMeshSimulatorManager

        OmniMeshSimulatorManager.toggle_simulator(context)
        return {"FINISHED"}


class LOD_OT_toggle_split_preview(Operator):
    """Toggle side-by-side interactive split preview comparison."""

    bl_idname = "lod_tool.toggle_split_preview"
    bl_label = "Toggle Split Preview"
    bl_options = {"REGISTER"}

    def execute(self, context: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        from .split_preview import OmniMeshSplitPreviewManager

        OmniMeshSplitPreviewManager.toggle_preview(context)
        return {"FINISHED"}


class LOD_OT_clean_and_repair_mesh(Operator):
    """Execute topology repair, hygiene, and normal healing on selected meshes."""

    bl_idname = "lod_tool.clean_and_repair_mesh"
    bl_label = "Clean & Repair Mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and get_selected_mesh_objects(context))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        mesh_objs = get_selected_mesh_objects(context)
        total_loose = 0
        total_deg = 0

        for obj in mesh_objs:
            bm = bmesh.new()
            try:
                bm.from_mesh(obj.data)
                res = MeshSanitizer.sanitize_mesh_full(
                    bm,
                    epsilon_merge=props.weld_distance if props.enable_weld_vertices else 1e-6,
                    w_crit=0.001,
                    enable_triangulate_ngons=props.enable_triangulate_ngons,
                    enable_split_non_manifold=props.enable_split_non_manifold,
                    enable_fill_holes=props.enable_fill_holes,
                    hole_max_edges=props.hole_max_edges,
                )
                total_loose += res.get("loose_verts_deleted", 0)
                total_deg += res.get("degenerate_faces_deleted", 0)
                bm.to_mesh(obj.data)
            finally:
                bm.free()
            obj.data.update()

        props.last_cleanup_summary = f"Cleaned: {total_loose} loose verts, {total_deg} degenerate faces."
        self.report({"INFO"}, props.last_cleanup_summary)
        return {"FINISHED"}


class LOD_OT_clean_and_repair_materials(Operator):
    """Execute material slot deduplication, orphan purge, and shader node cleanup."""

    bl_idname = "lod_tool.clean_and_repair_materials"
    bl_label = "Clean Materials & Slots"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and get_selected_mesh_objects(context))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        mesh_objs = get_selected_mesh_objects(context)
        purged_slots = 0
        merged_blocks = 0

        for obj in mesh_objs:
            if props.mat_cleanup_purge_unused_slots:
                purged_slots += MaterialOptimizer.purge_empty_and_unused_slots(obj)
            if props.mat_cleanup_merge_duplicate_datablocks:
                merged_blocks += MaterialOptimizer.merge_duplicate_materials_scene()
            if props.mat_cleanup_remove_orphan_nodes:
                MaterialOptimizer.clean_orphan_shader_nodes()

        props.last_material_cleanup_summary = f"Purged {purged_slots} unused slots, merged {merged_blocks} materials."
        self.report({"INFO"}, props.last_material_cleanup_summary)
        return {"FINISHED"}


class LOD_OT_import_pbr_set(Operator):
    """Import and construct PBR shader graph from texture maps."""

    bl_idname = "lod_tool.import_pbr_set"
    bl_label = "Import PBR Textures"
    bl_options = {"REGISTER", "UNDO"}

    if bpy:
        directory: Any = bpy.props.StringProperty(subtype="DIR_PATH")
        files: Any = bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)
    else:
        directory: Any = ""
        files: Any = None

    def execute(self, context: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        active_obj = context.active_object
        if not active_obj or active_obj.type != "MESH":
            self.report({"WARNING"}, "Please select a target mesh object.")
            return {"CANCELLED"}

        file_paths = []
        if self.files and self.directory:
            for f in self.files:
                file_paths.append(f"{self.directory}/{f.name}")

        mat = bpy.data.materials.new(name=f"M_{active_obj.name}")
        mat.use_nodes = True
        success = ShaderGraphBuilder.build_pbr_graph(mat, file_paths)
        if success:
            if len(active_obj.material_slots) == 0:
                active_obj.data.materials.append(mat)
            else:
                active_obj.material_slots[0].material = mat
            self.report({"INFO"}, f"Successfully built PBR shader '{mat.name}'")
            return {"FINISHED"}

        self.report({"WARNING"}, "No compatible PBR textures found.")
        return {"CANCELLED"}

    def invoke(self, context: Any, event: Any) -> set[str]:
        if bpy:
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}
        return {"FINISHED"}


class LOD_OT_auto_match_pbr_folder(Operator):
    """Scan directory and match texture sets to mesh material slots."""

    bl_idname = "lod_tool.auto_match_pbr_folder"
    bl_label = "Auto-Match PBR Folder"
    bl_options = {"REGISTER", "UNDO"}

    if bpy:
        directory: Any = bpy.props.StringProperty(subtype="DIR_PATH")
    else:
        directory: Any = ""

    def execute(self, context: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        active_obj = context.active_object
        if not active_obj or active_obj.type != "MESH":
            self.report({"WARNING"}, "Please select a target mesh object.")
            return {"CANCELLED"}

        if not self.directory:
            self.report({"WARNING"}, "Please choose a valid directory.")
            return {"CANCELLED"}

        matched = BatchMaterialSlotMatcher.match_directory_to_slots(active_obj, self.directory)
        count = 0
        for slot_name, tex_dict in matched.items():
            slot_mat = None
            for slot in active_obj.material_slots:
                if slot.name == slot_name:
                    slot_mat = slot.material
                    break
            if not slot_mat:
                slot_mat = bpy.data.materials.new(name=slot_name)
                slot_mat.use_nodes = True
                active_obj.data.materials.append(slot_mat)
            if ShaderGraphBuilder.build_pbr_graph(slot_mat, list(tex_dict.values())):
                count += 1

        self.report({"INFO"}, f"Matched and populated {count} material slots from folder.")
        return {"FINISHED"}

    def invoke(self, context: Any, event: Any) -> set[str]:
        if bpy:
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}
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

        self.report({"INFO"}, f"Synchronized settings across {copied} object(s).")
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
            self.report({"INFO"}, f"Selected master asset: {master_name}")
            return {"FINISHED"}

        return {"CANCELLED"}


OPERATOR_CLASSES = [
    LOD_OT_inspect_lod0,
    LOD_OT_analyze_and_configure,
    LOD_OT_sync_selection_settings,
    LOD_OT_select_master_asset,
    LOD_OT_clean_and_repair_mesh,
    LOD_OT_clean_and_repair_materials,
    LOD_OT_import_pbr_set,
    LOD_OT_auto_match_pbr_folder,
    LOD_OT_generate_all,
    LOD_OT_generate_impostor,
    LOD_OT_remove_impostor,
    LOD_OT_generate_collision_hulls,
    LOD_OT_remove_collision_hulls,
    LOD_OT_preview_tier,
    LOD_OT_toggle_simulator,
    LOD_OT_toggle_split_preview,
]


def register_operators():
    if not bpy:
        return
    for cls in OPERATOR_CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass


def unregister_operators():
    if not bpy:
        return
    for cls in reversed(OPERATOR_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except (ValueError, RuntimeError):
            pass
