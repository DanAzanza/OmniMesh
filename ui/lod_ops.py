# pyright: reportInvalidTypeForm=none
"""
Core LOD Generation, Configuration, Tier Preview, and Selection Synchronization Operators.
Generation engine logic is modularized in core.lod_generator; preset operators in ui.lod_preset_ops.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.types import Operator
else:
    try:
        import bpy
        from bpy.types import Operator
    except ImportError:
        bpy = None
        Operator = object

try:
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
        get_asset_existing_lods,
        get_associated_armature,
        get_available_asset_names,
        get_selected_mesh_objects,
        is_object_valid,
        resolve_effective_asset_name,
        resolve_lod_context,
        safe_report,
        tag_view3d_redraw,
    )
except (ImportError, ValueError):
    from core.lod_generator import generate_all_lods
    from core.metrics import (
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
        get_asset_existing_lods,
        get_associated_armature,
        get_available_asset_names,
        get_selected_mesh_objects,
        is_object_valid,
        resolve_effective_asset_name,
        resolve_lod_context,
        safe_report,
        tag_view3d_redraw,
    )


class LOD_OT_reset_to_preset(Operator):
    """Reset LOD tiers and parameters to the active preset defaults."""

    bl_idname = "lod_tool.reset_to_preset"
    bl_label = "Reset to Preset"
    bl_description = "Resets all tier budgets and transition metrics back to the active preset defaults"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[Any]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        project_preset_tiers(props, context, ignore_cache=True)
        props.lod_preset_is_dirty = False
        tag_view3d_redraw(context)
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

    def execute(self, context: Any) -> set[Any]:
        if not bpy or not context:
            return {"FINISHED"}
        props, target_obj, is_deriv = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        project_preset_tiers(props, context)
        tag_view3d_redraw(context)
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

    def execute(self, context: Any) -> set[Any]:
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

        bdata = getattr(context, "blend_data", None) or (bpy.data if bpy and hasattr(bpy, "data") else None)
        if bdata is None:
            return {"CANCELLED"}
        success, msg = generate_all_lods(
            context=context,
            props=props,
            mesh_objs=mesh_objs,
            armature_obj=armature_obj,
            base_name=base_name,
            only_out_of_sync=bool(self.only_out_of_sync),
            blend_data=bdata,
        )

        if success:
            tag_view3d_redraw(context)
            safe_report(self, {"INFO"}, msg)
            return {"FINISHED"}
        else:
            safe_report(self, {"ERROR"}, msg)
            return {"CANCELLED"}


class LOD_OT_add_lod_tier(Operator):
    """Append a new LOD tier to the active configuration."""

    bl_idname = "lod_tool.add_lod_tier"
    bl_label = "Add LOD Tier"
    bl_description = "Appends a new LOD tier to the current configuration"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[Any]:
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
        tag_view3d_redraw(context)
        safe_report(self, {"INFO"}, f"Added {item.name}.")
        return {"FINISHED"}


class LOD_OT_remove_lod_tier(Operator):
    """Remove the active or specified LOD tier from configuration."""

    bl_idname = "lod_tool.remove_lod_tier"
    bl_label = "Remove LOD Tier"
    bl_description = "Removes the selected LOD tier from configuration"
    bl_options = {"REGISTER", "UNDO"}

    tier_index: bpy.props.IntProperty(name="Tier Index", default=-1) if bpy else -1

    def execute(self, context: Any) -> set[Any]:
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
        tag_view3d_redraw(context)
        safe_report(self, {"INFO"}, f"Removed {removed_name}.")
        return {"FINISHED"}


class LOD_OT_sync_selection_settings(Operator):
    """Copy LOD tool settings from active master mesh to all selected objects."""

    bl_idname = "lod_tool.sync_selection_settings"
    bl_label = "Copy Settings to Selection"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[Any]:
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
                other_props.impostor_render_underside = props.impostor_render_underside
                other_props.impostor_grid_size = props.impostor_grid_size
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

    def execute(self, context: Any) -> set[Any]:
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


class LOD_OT_toggle_side_by_side(Operator):
    """Place all generated LOD tiers side-by-side along the X-axis for visual inspection, or restore original positions."""

    bl_idname = "lod_tool.toggle_side_by_side"
    bl_label = "Toggle Side-by-Side LOD View"
    bl_description = (
        "Place all generated LOD tiers side-by-side along the X-axis for simultaneous inspection, or restore alignment"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[Any]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        view_layer = context.view_layer
        is_active = bool(getattr(props, "is_side_by_side_active", False))

        active_asset = getattr(props, "active_asset", "")
        if active_asset and active_asset != "ALL":
            target_assets = [active_asset]
        else:
            target_assets = get_available_asset_names(context)
            if not target_assets:
                eff = resolve_effective_asset_name(context, props)
                if eff:
                    target_assets = [eff]

        if not target_assets:
            safe_report(self, {"WARNING"}, "No assets found in scene for side-by-side inspection.")
            return {"CANCELLED"}

        if is_active:
            restored = 0
            for asset_name in target_assets:
                existing = get_asset_existing_lods(context, asset_name)
                for tier_idx, info in existing.items():
                    coll = bpy.data.collections.get(info.get("collection_name", ""))
                    is_lod0 = tier_idx == 0
                    if coll:
                        coll.hide_viewport = not is_lod0
                    for obj in info.get("meshes", []):
                        if not is_object_valid(obj):
                            continue
                        if "_om_sbs_orig_x" in obj:
                            try:
                                obj.location.x = float(obj["_om_sbs_orig_x"])
                                del obj["_om_sbs_orig_x"]
                            except (KeyError, ValueError, TypeError) as exc:
                                logger.debug("Could not restore object X location: %s", exc)
                        if "_om_sbs_orig_y" in obj:
                            try:
                                obj.location.y = float(obj["_om_sbs_orig_y"])
                                del obj["_om_sbs_orig_y"]
                            except (KeyError, ValueError, TypeError) as exc:
                                logger.debug("Could not restore object Y location: %s", exc)
                        obj.hide_set(not is_lod0, view_layer=view_layer)
                        restored += 1

            props.is_side_by_side_active = False
            safe_report(self, {"INFO"}, f"Restored LOD alignment to original positions ({restored} objects).")
        else:
            total_tiers_found = 0
            for asset_name in target_assets:
                existing = get_asset_existing_lods(context, asset_name)
                if len(existing) >= 2:
                    total_tiers_found += len(existing)

            if total_tiers_found < 2:
                safe_report(
                    self, {"WARNING"}, "At least 2 generated LOD tiers are required for side-by-side inspection."
                )
                return {"CANCELLED"}

            arranged = 0
            for asset_idx, asset_name in enumerate(target_assets):
                existing = get_asset_existing_lods(context, asset_name)
                if len(existing) < 2:
                    continue

                lod0_info = existing.get(0)
                lod0_objs = lod0_info.get("meshes", []) if lod0_info else []
                dim_x = max(
                    (float(getattr(getattr(o, "dimensions", None), "x", 2.0)) for o in lod0_objs),
                    default=2.0,
                )
                dim_y = max(
                    (float(getattr(getattr(o, "dimensions", None), "y", 2.0)) for o in lod0_objs),
                    default=2.0,
                )
                dim_x = 2.0 if dim_x <= 0.05 else dim_x
                dim_y = 2.0 if dim_y <= 0.05 else dim_y

                spacing_x = max(dim_x * 1.4, dim_x + 0.5, 1.5)
                spacing_y = max(dim_y * 1.4, dim_y + 0.5, 1.5)
                offset_y = float(asset_idx) * spacing_y

                for tier_order, tier_idx in enumerate(sorted(existing.keys())):
                    offset_x = float(tier_order) * spacing_x
                    info = existing[tier_idx]
                    coll = bpy.data.collections.get(info.get("collection_name", ""))
                    if coll:
                        coll.hide_viewport = False

                    for obj in info.get("meshes", []):
                        if not is_object_valid(obj):
                            continue
                        if "_om_sbs_orig_x" not in obj:
                            obj["_om_sbs_orig_x"] = float(obj.location.x)
                        if "_om_sbs_orig_y" not in obj:
                            obj["_om_sbs_orig_y"] = float(obj.location.y)

                        obj.location.x = float(obj["_om_sbs_orig_x"]) + offset_x
                        obj.location.y = float(obj["_om_sbs_orig_y"]) + offset_y
                        obj.hide_set(False, view_layer=view_layer)
                        arranged += 1

            props.is_side_by_side_active = True
            safe_report(self, {"INFO"}, f"Side-by-side inspection active: arranged {arranged} objects across tiers.")

        tag_view3d_redraw(context)

        return {"FINISHED"}


LOD_OPERATOR_CLASSES = (
    LOD_OT_reset_to_preset,
    LOD_OT_analyze_and_configure,
    LOD_OT_generate_all,
    LOD_OT_add_lod_tier,
    LOD_OT_remove_lod_tier,
    LOD_OT_sync_selection_settings,
    LOD_OT_select_master_asset,
    LOD_OT_toggle_side_by_side,
)

__all__ = [
    "LOD_OPERATOR_CLASSES",
    "LOD_OT_reset_to_preset",
    "LOD_OT_analyze_and_configure",
    "LOD_OT_generate_all",
    "LOD_OT_add_lod_tier",
    "LOD_OT_remove_lod_tier",
    "LOD_OT_sync_selection_settings",
    "LOD_OT_select_master_asset",
    "LOD_OT_toggle_side_by_side",
    "LOD_OT_add_preset_tier",
    "LOD_OT_remove_preset_tier",
    "LOD_OT_save_preset_tiers",
    "LOD_OT_apply_preset_tiers",
    "LOD_OT_capture_scene_tiers",
]
