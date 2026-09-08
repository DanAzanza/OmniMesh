"""
Core LOD Generation, Configuration, Tier Preview, and Selection Synchronization Operators.
Generation engine logic is modularized in core.lod_generator; preset operators in ui.lod_preset_ops.
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bpy
    from bpy.types import Operator
except ImportError:
    bpy = None
    Operator = object

try:
    from core.lod_generator import generate_all_lods
    from core.metrics import (
        compute_distance_from_screen_size,
        compute_vertical_fov,
    )
    from ui.lod_preset_ops import (
        LOD_OT_add_preset_tier,
        LOD_OT_apply_preset_tiers,
        LOD_OT_capture_scene_tiers,
        LOD_OT_remove_preset_tier,
        LOD_OT_save_preset_tiers,
    )
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
    from ..core.lod_generator import generate_all_lods
    from ..core.metrics import (
        compute_distance_from_screen_size,
        compute_vertical_fov,
    )
    from .lod_preset_ops import (
        LOD_OT_add_preset_tier,
        LOD_OT_apply_preset_tiers,
        LOD_OT_capture_scene_tiers,
        LOD_OT_remove_preset_tier,
        LOD_OT_save_preset_tiers,
    )
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
            f"Configured {len(props.lods)} LOD tiers for '{props.export_base_name}' "
            f"(Radius: {props.bounding_radius:.2f}m, Base Tris: {props.base_triangles:,})",
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

        base_name = (
            asset_name
            or props.export_base_name
            or (context.active_object.name if context.active_object else mesh_objs[0].name)
        )
        base_name = base_name.split("_LOD")[0]

        success, msg = generate_all_lods(
            context=context,
            props=props,
            mesh_objs=mesh_objs,
            armature_obj=armature_obj,
            base_name=base_name,
            only_out_of_sync=bool(self.only_out_of_sync),
        )

        if success:
            safe_report(self, {"INFO"}, msg)
            return {"FINISHED"}
        else:
            safe_report(self, {"ERROR"}, msg)
            return {"CANCELLED"}


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

        if 0 <= self.tier_index < len(props.lods):
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
)

__all__ = [
    "LOD_OPERATOR_CLASSES",
    "LOD_OT_reset_to_preset",
    "LOD_OT_analyze_and_configure",
    "LOD_OT_generate_all",
    "LOD_OT_solo_tier",
    "LOD_OT_add_lod_tier",
    "LOD_OT_remove_lod_tier",
    "LOD_OT_preview_tier",
    "LOD_OT_sync_selection_settings",
    "LOD_OT_select_master_asset",
    "LOD_OT_add_preset_tier",
    "LOD_OT_remove_preset_tier",
    "LOD_OT_save_preset_tiers",
    "LOD_OT_apply_preset_tiers",
    "LOD_OT_capture_scene_tiers",
]
