"""
Master Pipeline Operators for OmniMesh LOD Analysis, Generation, Collision, and Viewport Preview.
"""

from __future__ import annotations

import math
from typing import Any

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
    from ..core.rigging import KinematicBonePruner, WeightSanitizer
    from ..core.sanitizer import MeshSanitizer
except (ImportError, ValueError):
    from core.collision import CollisionManager
    from core.decimator import MeshDecimator
    from core.hierarchy import MeshMergeEngine
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

        props = context.scene.lod_tool
        all_coords = []
        for obj in mesh_objs:
            all_coords.extend([obj.matrix_world @ v.co for v in obj.data.vertices])

        if not all_coords:
            self.report({"ERROR"}, "Selected meshes have no vertices.")
            return {"CANCELLED"}

        center, radius = compute_bounding_sphere(all_coords)

        render = context.scene.render
        cam = context.scene.camera
        cam_angle = cam.data.angle if cam and cam.type == "CAMERA" else math.radians(60.0)
        sensor_fit = cam.data.sensor_fit if cam and cam.type == "CAMERA" else "AUTO"
        aspect_ratio = render.resolution_x / max(1, render.resolution_y)
        fov_v = compute_vertical_fov(cam_angle, aspect_ratio, sensor_fit)

        total_base_tris = sum(len(obj.data.polygons) for obj in mesh_objs)

        if props.progression_mode == "LOGARITHMIC":
            tiers_data = generate_logarithmic_screen_tiers(
                lod_count=props.lod_count,
                base_screen_pct=100.0,
                min_screen_pct=5.0,
                base_tris=total_base_tris,
                gamma=1.5,
            )
        else:
            step = 95.0 / max(1, props.lod_count - 1)
            tiers_data = []
            for i in range(props.lod_count):
                s_pct = max(5.0, 100.0 - (i * step))
                s_frac = s_pct / 100.0
                t_tris = int(round(total_base_tris * (s_frac**1.5)))
                tiers_data.append((f"LOD{i}", s_pct, t_tris))

        props.lods.clear()
        for i, (name, s_pct, t_tris) in enumerate(tiers_data):
            item = props.lods.add()
            item.name = name
            item.lod_index = i
            item.screen_size_pct = s_pct
            item.target_tris = t_tris
            item.actual_tris = total_base_tris if i == 0 else 0

            s_frac = s_pct / 100.0
            dist = compute_distance_from_screen_size(radius, s_frac, fov_v)
            tolerances = compute_coupled_tolerances(radius, s_frac, 1.5, render.resolution_y)

            item.distance_m = dist
            item.delta_world = tolerances["delta_world"]
            item.mat_slots_count = sum(len(obj.material_slots) for obj in mesh_objs)

        if not props.export_base_name:
            props.export_base_name = mesh_objs[0].name.split("_LOD")[0]

        self.report(
            {"INFO"},
            f"Configured {len(props.lods)} LOD tiers for '{props.export_base_name}' ({total_base_tris:,} base tris, radius={radius:.2f}m)",
        )
        return {"FINISHED"}


class LOD_OT_generate_all(Operator):
    """Execute complete LOD generation pipeline across all configured tiers."""

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

        props = context.scene.lod_tool
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
                        target_coll.objects.link(lod_obj)

                        if i == 0:
                            bm = bmesh.new()
                            bm.from_mesh(lod_obj.data)
                            MeshSanitizer.clean_loose_and_degenerates(bm)
                            bm.to_mesh(lod_obj.data)
                            bm.free()
                        else:
                            if props.purge_distant_shape_keys and i >= 2:
                                MeshDecimator.prepare_and_clean_shape_keys(lod_obj, purge=True)

                            bm = bmesh.new()
                            bm.from_mesh(lod_obj.data)
                            MeshSanitizer.sanitize_mesh_full(bm, tolerances["epsilon_merge"], tolerances["w_crit"])

                            # Occlusion & Interior Geometry Culling
                            if props.enable_occlusion_culling and i >= props.occlusion_lod_start:
                                cull_res = HardenedOcclusionCuller.cull_interior_faces(
                                    lod_obj,
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
                            MeshDecimator.inject_curvature_weights(lod_obj, bm, pinned_verts)
                            bm.to_mesh(lod_obj.data)
                            bm.free()
                            lod_obj.data.update()

                            MeshDecimator.execute_decimate_qem(
                                lod_obj, tolerances["qem_ratio"], use_curvature_weight=True
                            )

                            if props.consolidate_materials:
                                MaterialOptimizer.consolidate_micro_materials(
                                    lod_obj,
                                    area_crit=tolerances["area_crit"],
                                )

                            if props.reproject_normals:
                                NormalManager.reproject_custom_split_normals(
                                    lod_obj, source_obj, tolerances["delta_world"]
                                )

                            if armature_obj and len(lod_obj.vertex_groups) > 0:
                                if props.enable_leaf_bone_pruning and i >= props.leaf_bone_lod_start:
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
                    tier.mat_slots_count = tier_mats

            props.last_culled_faces_count = total_culled_faces
            props.last_culled_islands_count = total_culled_islands

            # Compute and record summary metrics
            if len(props.lods) > 0:
                base_tris_val = props.lods[0].actual_tris or props.lods[0].target_tris or 1
                final_tris_val = props.lods[-1].actual_tris or props.lods[-1].target_tris or 1
                reduction_pct = max(0.0, (1.0 - final_tris_val / float(base_tris_val)) * 100.0)

                props.last_generated_base_tris = base_tris_val
                props.last_generated_final_tris = final_tris_val
                props.last_generated_reduction_pct = reduction_pct
                props.last_generated_tier_count = len(props.lods)

            self.report(
                {"INFO"}, f"Generated {len(props.lods)} LOD tiers across {len(mesh_objs)} objects in '{coll_name}'"
            )
            return {"FINISHED"}
        finally:
            if armature_obj and orig_pose_pos and hasattr(armature_obj.data, "pose_position"):
                armature_obj.data.pose_position = orig_pose_pos


class LOD_OT_generate_collision_hulls(Operator):
    """Generate multi-convex physics collision hulls for selected mesh objects."""

    bl_idname = "lod_tool.generate_collision_hulls"
    bl_label = "Generate Collision Hulls"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            self.report({"WARNING"}, "No mesh objects selected for collision generation.")
            return {"CANCELLED"}

        props = context.scene.lod_tool
        base_name = props.export_base_name or mesh_objs[0].name.split("_LOD")[0]

        colliders = CollisionManager.generate_colliders_for_objects(
            mesh_objs=mesh_objs,
            base_name=base_name,
            hull_count=int(props.collision_hull_count),
            max_verts_per_hull=int(props.collision_max_verts_per_hull),
            concavity_threshold=float(props.collision_concavity_threshold),
            mode=props.collision_decomposition_mode,
        )

        props.last_generated_collider_count = len(colliders)
        self.report(
            {"INFO"},
            f"Generated {len(colliders)} convex collision hulls in collection '{base_name}_Colliders'",
        )
        return {"FINISHED"}


class LOD_OT_remove_collision_hulls(Operator):
    """Remove and purge all collision hulls for active asset."""

    bl_idname = "lod_tool.remove_collision_hulls"
    bl_label = "Remove Collision Hulls"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        mesh_objs = get_selected_mesh_objects(context)
        props = context.scene.lod_tool
        base_name = props.export_base_name or (mesh_objs[0].name.split("_LOD")[0] if mesh_objs else "")

        removed = CollisionManager.remove_colliders_for_objects(mesh_objs, base_name)
        props.last_generated_collider_count = 0
        self.report({"INFO"}, f"Removed {removed} collision objects for '{base_name}'")
        return {"FINISHED"}


class LOD_OT_preview_tier(Operator):
    """Isolate and display selected LOD tier geometry in 3D Viewport."""

    bl_idname = "lod_tool.preview_tier"
    bl_label = "Preview Tier"
    bl_options = {"REGISTER", "UNDO"}

    tier_index: bpy.props.IntProperty(name="Tier Index", default=0, min=0) if bpy else 0  # type: ignore

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        props = context.scene.lod_tool
        if not props.lods or self.tier_index >= len(props.lods):
            self.report({"WARNING"}, f"LOD tier {self.tier_index} not generated.")
            return {"CANCELLED"}

        mesh_objs = get_selected_mesh_objects(context)
        base_name = props.export_base_name or (mesh_objs[0].name.split("_LOD")[0] if mesh_objs else "")
        coll_name = f"{base_name}_LODs"
        target_coll = bpy.data.collections.get(coll_name)
        if not target_coll:
            self.report({"WARNING"}, f"LOD collection '{coll_name}' not found.")
            return {"CANCELLED"}

        for obj in target_coll.objects:
            if "_LOD" in obj.name:
                is_target = f"_LOD{self.tier_index}" in obj.name
                obj.hide_viewport = not is_target
                obj.hide_render = not is_target

        self.report({"INFO"}, f"Previewing LOD{self.tier_index}")
        return {"FINISHED"}


class LOD_OT_toggle_simulator(Operator):
    """Toggle real-time distance-based Viewport LOD simulator loop."""

    bl_idname = "lod_tool.toggle_simulator"
    bl_label = "Toggle LOD Simulator"
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
    LOD_OT_generate_all,
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
