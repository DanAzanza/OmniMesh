"""
N-Panel User Interface & Master Operators for OmniMesh with Multi-Mesh, Rigging & Real-Time Simulator.
"""

from __future__ import annotations

import math
from typing import Any

try:
    import bmesh
    import bpy
    from bpy.types import Operator, Panel, UIList
except ImportError:
    bpy = None
    bmesh = None
    Panel = object
    Operator = object
    UIList = object

try:
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
    from ..core.rigging import KinematicBonePruner, WeightSanitizer
    from ..core.sanitizer import MeshSanitizer
except (ImportError, ValueError):
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
    from core.rigging import KinematicBonePruner, WeightSanitizer
    from core.sanitizer import MeshSanitizer


class LOD_UL_tier_list(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            row.label(text=f"LOD{item.lod_index}", icon="MESH_DATA")
            row.prop(item, "screen_size_pct", text="", emboss=False)
            if item.actual_tris > 0:
                row.label(text=f"{item.actual_tris:,} tris")
            else:
                row.label(text=f"~{item.target_tris:,} tris")
            row.label(text=f"{item.distance_m:.1f}m")
            row.label(text=f"{item.mat_slots_count} mat", icon="MATERIAL")


def get_selected_mesh_objects(context: Any) -> list[Any]:
    if not bpy or not context:
        return []
    meshes = [obj for obj in context.selected_objects if obj.type == "MESH"]
    if not meshes and context.active_object and context.active_object.type == "MESH":
        meshes = [context.active_object]
    return meshes


def get_associated_armature(mesh_objs: list[Any]) -> Any:
    for obj in mesh_objs:
        if obj.parent and obj.parent.type == "ARMATURE":
            return obj.parent
        for mod in obj.modifiers:
            if mod.type == "ARMATURE" and mod.object:
                return mod.object
    return None


class LOD_OT_analyze_and_configure(Operator):
    bl_idname = "lod_tool.analyze_and_configure"
    bl_label = "Analyze & Auto-Configure"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bpy and len(get_selected_mesh_objects(context)) > 0

    def execute(self, context):
        props = context.scene.lod_tool
        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        all_coords = []
        base_tris = 0
        total_mat_slots = 0

        for obj in mesh_objs:
            m_w = obj.matrix_world
            all_coords.extend([m_w @ v.co for v in obj.data.vertices])
            base_tris += len(obj.data.polygons)
            total_mat_slots += len(obj.material_slots)

        _, radius = compute_bounding_sphere(all_coords)

        if not props.export_base_name:
            primary_name = context.active_object.name if context.active_object else mesh_objs[0].name
            props.export_base_name = primary_name.split("_LOD")[0]

        render = context.scene.render
        aspect_ratio = render.resolution_x / max(1, render.resolution_y)
        cam = context.scene.camera
        cam_angle = cam.data.angle if cam and cam.type == "CAMERA" else math.radians(60.0)
        sensor_fit = cam.data.sensor_fit if cam and cam.type == "CAMERA" else "AUTO"
        fov_v = compute_vertical_fov(cam_angle, aspect_ratio, sensor_fit)

        if props.target_engine == "MSFS_2024":
            props.num_lods = 7
            screen_tiers = [100.0, 50.0, 25.0, 10.0, 5.0, 2.0, 0.5]
        else:
            screen_tiers = generate_logarithmic_screen_tiers(props.num_lods, props.cull_screen_size_pct)

        props.lods.clear()
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
            item.mat_slots_count = total_mat_slots if i < 2 else max(1, total_mat_slots - (i - 1))

        self.report(
            {"INFO"},
            f"Configured {len(props.lods)} LOD tiers for {len(mesh_objs)} meshes (Radius: {radius:.2f}m, Base Tris: {base_tris:,})",
        )
        return {"FINISHED"}


class LOD_OT_generate_all(Operator):
    bl_idname = "lod_tool.generate_all"
    bl_label = "Generate All LODs"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bpy and len(get_selected_mesh_objects(context)) > 0 and len(context.scene.lod_tool.lods) > 0

    def execute(self, context):
        props = context.scene.lod_tool
        mesh_objs = get_selected_mesh_objects(context)
        armature_obj = get_associated_armature(mesh_objs)

        orig_pose_pos = None
        if armature_obj and hasattr(armature_obj.data, "pose_position"):
            orig_pose_pos = armature_obj.data.pose_position
            armature_obj.data.pose_position = "REST"

        base_name = props.export_base_name or (
            context.active_object.name if context.active_object else mesh_objs[0].name
        )
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
            tolerances = compute_coupled_tolerances(radius, s_frac, props.tau_sse, render.resolution_y)
            should_merge = props.hierarchy_mode == "MERGE_AT_TIER" and i >= props.merge_start_tier

            tier_obj = None

            if should_merge and len(mesh_objs) > 1:
                merged_name = f"{base_name}_LOD{i}"
                existing = bpy.data.objects.get(merged_name)
                if existing:
                    bpy.data.objects.remove(existing, do_unlink=True)

                tier_obj = MeshMergeEngine.consolidate_and_merge_meshes(mesh_objs, merged_name, armature_obj)
                target_coll.objects.link(tier_obj)

                bm = bmesh.new()
                bm.from_mesh(tier_obj.data)
                MeshSanitizer.sanitize_mesh_full(bm, tolerances["epsilon_merge"], tolerances["w_crit"])
                pinned_verts = MeshDecimator.tag_boundaries_and_uv_seams(bm)
                MeshDecimator.apply_planar_limited_dissolve(bm, math.radians(tolerances["planar_angle_deg"]))
                MeshDecimator.inject_curvature_weights(tier_obj, bm, pinned_verts)
                bm.to_mesh(tier_obj.data)
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
                tier.mat_slots_count = len(tier_obj.material_slots)
                tier.generated_obj = tier_obj
                generated_tier_objects.append(tier_obj)

            else:
                tier_tris = 0
                tier_mats = 0
                for obj_idx, source_obj in enumerate(mesh_objs):
                    sub_name = f"{source_obj.name}_LOD{i}" if len(mesh_objs) > 1 else f"{base_name}_LOD{i}"
                    existing = bpy.data.objects.get(sub_name)
                    if existing and existing != source_obj:
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
                        if props.purge_shape_keys and i >= 2:
                            MeshDecimator.prepare_and_clean_shape_keys(lod_obj, purge=True)

                        bm = bmesh.new()
                        bm.from_mesh(lod_obj.data)
                        MeshSanitizer.sanitize_mesh_full(bm, tolerances["epsilon_merge"], tolerances["w_crit"])
                        pinned_verts = MeshDecimator.tag_boundaries_and_uv_seams(bm)
                        MeshDecimator.apply_planar_limited_dissolve(bm, math.radians(tolerances["planar_angle_deg"]))
                        MeshDecimator.inject_curvature_weights(lod_obj, bm, pinned_verts)
                        bm.to_mesh(lod_obj.data)
                        bm.free()
                        lod_obj.data.update()

                        MeshDecimator.execute_decimate_qem(lod_obj, tolerances["qem_ratio"], use_curvature_weight=True)

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
                tier.mat_slots_count = tier_mats

        if armature_obj and orig_pose_pos:
            armature_obj.data.pose_position = orig_pose_pos

        self.report({"INFO"}, f"Generated {len(props.lods)} LOD tiers across {len(mesh_objs)} objects in '{coll_name}'")
        return {"FINISHED"}


class LOD_OT_preview_tier(Operator):
    bl_idname = "lod_tool.preview_tier"
    bl_label = "Preview Selected Tier"
    bl_options = {"REGISTER", "UNDO"}

    tier_index: bpy.props.IntProperty(default=0) if bpy else 0

    def execute(self, context):
        if not bpy:
            return {"FINISHED"}
        props = context.scene.lod_tool
        target_idx = self.tier_index
        base_name = props.export_base_name

        coll = bpy.data.collections.get(f"{base_name}_LODs")
        if coll:
            for obj in coll.objects:
                is_this_tier = f"_LOD{target_idx}" in obj.name
                obj.hide_viewport = not is_this_tier
                obj.hide_render = not is_this_tier

        props.active_lod_index = target_idx
        return {"FINISHED"}


class LOD_PT_main_panel(Panel):
    bl_label = "OmniMesh"
    bl_idname = "LOD_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OmniMesh"

    def draw(self, context):
        if not bpy:
            return
        layout = self.layout
        props = context.scene.lod_tool

        box = layout.box()
        box.label(text="Project & Engine Target", icon="SCENE_DATA")
        box.prop(props, "target_engine", text="")
        box.prop(props, "asset_category", text="")
        box.prop(props, "export_base_name", text="Asset Name")

        box = layout.box()
        box.label(text="Hierarchy & Draw-Call Optimization", icon="OUTLINER_OB_GROUP_INSTANCE")
        box.prop(props, "hierarchy_mode", text="")
        if props.hierarchy_mode == "MERGE_AT_TIER":
            box.prop(props, "merge_start_tier")

        box = layout.box()
        box.label(text="Rigging & Skeletal Optimization", icon="ARMATURE_DATA")
        box.prop(props, "max_bone_influences")
        box.prop(props, "enable_bone_pruning")
        box.prop(props, "purge_shape_keys")

        box = layout.box()
        box.label(text="Quality & Screen-Space Error", icon="RESTRICT_VIEW_OFF")
        box.prop(props, "tau_sse", slider=True)
        box.prop(props, "cull_screen_size_pct", slider=True)
        if props.target_engine != "MSFS_2024":
            box.prop(props, "num_lods")
        box.prop(props, "preserve_slot_indexing")

        col = layout.column(align=True)
        col.scale_y = 1.2
        col.operator("lod_tool.analyze_and_configure", icon="VIEWZOOM")

        if len(props.lods) > 0:
            box = layout.box()
            box.label(text="Configured LOD Tiers", icon="MOD_DECIM")
            box.template_list("LOD_UL_tier_list", "", props, "lods", props, "active_lod_index", rows=len(props.lods))

            col = layout.column(align=True)
            col.scale_y = 1.4
            col.operator("lod_tool.generate_all", icon="GEOMETRY_NODES")

            box = layout.box()
            box.label(text="Isolate Viewport LOD", icon="HIDE_OFF")
            row = box.row(align=True)
            for i, _tier in enumerate(props.lods):
                op = row.operator("lod_tool.preview_tier", text=f"LOD{i}")
                op.tier_index = i

        # Real-Time Viewport LOD Simulator Section
        box = layout.box()
        box.label(text="Real-Time LOD Simulator", icon="PLAY")

        row = box.row(align=True)
        row.scale_y = 1.3
        if props.is_simulator_running:
            row.operator("lod_tool.toggle_live_simulator", text="Stop Simulation", icon="CANCEL")
        else:
            row.operator("lod_tool.toggle_live_simulator", text="Start Live Simulator", icon="PLAY")

        box.prop(props, "simulator_mode", text="Mode")

        if props.simulator_mode == "VIRTUAL_SLIDER":
            box.prop(props, "virtual_screen_size_pct", slider=True)
            box.prop(props, "virtual_preview_dist_m")

        box = layout.box()
        box.label(text="Multi-Engine Export", icon="EXPORT")
        box.prop(props, "export_directory")
        col = box.column(align=True)
        col.scale_y = 1.2
        col.operator("lod_tool.export_engine_package", icon="PACKAGE")


classes = (
    LOD_UL_tier_list,
    LOD_OT_analyze_and_configure,
    LOD_OT_generate_all,
    LOD_OT_preview_tier,
    LOD_PT_main_panel,
)


def register_panel():
    if not bpy:
        return
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister_panel():
    if not bpy:
        return
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
