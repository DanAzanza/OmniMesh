"""
OmniMesh Modular Panel Architecture for Blender 4.2+ and 5.2 LTS.
Structured into streamlined sequential workflow panels with gear-icon popovers:
1. Import (PBR Texture Set Importer & Multi-Slot Auto-Matcher)
2. Modify (Base Mesh Sanitization, Modifiers, and Material Cleanup)
3. LODs (Tier Configuration, Responsive UIList, Decimation & Testing Subpanel)
4. Engine Export (Multi-Engine Package Export, Live Bridge & Batch Ingestion)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bpy
    from bpy.types import Panel
except ImportError:
    bpy = None
    Panel = object

try:
    from ..core.lod_presets import (
        DEFAULT_LOD_PRESET_ID,
        LODPresetManager,
    )
    from ..core.pbr_presets import (
        DEFAULT_PRESET_ID,
        PBRExportPresetManager,
        PBRImportPresetManager,
    )
    from .operators import resolve_lod_context
    from .popovers import POPOVER_CLASSES
    from .utils import get_asset_base_meshes, resolve_effective_asset_name
except (ImportError, ValueError):
    from core.lod_presets import (
        DEFAULT_LOD_PRESET_ID,
        LODPresetManager,
    )
    from core.pbr_presets import (
        DEFAULT_PRESET_ID,
        PBRExportPresetManager,
        PBRImportPresetManager,
    )
    from ui.operators import resolve_lod_context
    from ui.popovers import POPOVER_CLASSES
    from ui.utils import get_asset_base_meshes, resolve_effective_asset_name


# =========================================================================
# PANEL 1: IMPORT
# =========================================================================


class OMNIMESH_PT_import(Panel):
    """Panel 1: PBR Texture Set Importer and Folder Auto-Matcher."""

    bl_label = "1. Import"
    bl_idname = "OMNIMESH_PT_import"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OmniMesh"
    bl_order = 0

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        box_pbr = layout.box()
        box_pbr.label(text="PBR Texture Set Importer", icon="IMAGE_DATA")

        # Row 1: [ Preset Dropdown ▾ ] [ 📋 Copy ] [ ❌ Delete ] [ ⚙️ Gear ]
        raw_preset = getattr(props, "pbr_import_preset", "")
        preset_id = str(raw_preset).strip() or DEFAULT_PRESET_ID
        is_builtin = PBRImportPresetManager.is_builtin(preset_id)

        row_preset = box_pbr.row(align=True)
        row_preset.use_property_split = False
        row_preset.prop(props, "pbr_import_preset", text="Preset")
        op_dup_imp = row_preset.operator("lod_tool.duplicate_preset", text="", icon="DUPLICATE")
        op_dup_imp.preset_type = "IMPORT"

        sub_del = row_preset.row(align=True)
        sub_del.enabled = not is_builtin
        sub_del.operator("lod_tool.delete_import_preset", text="", icon="X")
        row_preset.popover(panel="OMNIMESH_PT_popover_import_preset", icon="PREFERENCES", text="")

        # Row 2: [ Import ] [ Path Field ][ 📁 ]
        row2 = box_pbr.row(align=True)
        row2.use_property_split = False
        row2.scale_y = 1.15
        row2.operator("lod_tool.import_pbr_set", text="Import PBR Textures", icon="IMPORT")
        row2.prop(props, "pbr_import_directory", text="")

        if props.last_pbr_import_summary:
            box_pbr.label(text=props.last_pbr_import_summary, icon="CHECKMARK")


# =========================================================================
# PANEL 2: MODIFY (Base Prep, Sanitization, Modifiers & Materials)
# =========================================================================


class OMNIMESH_PT_modify(Panel):
    """Panel 2: Base Mesh Sanitization, Modifiers, and Material Cleanup."""

    bl_label = "2. Modify"
    bl_idname = "OMNIMESH_PT_modify"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OmniMesh"
    bl_order = 1

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        # 1. Action Row 1: Mesh Sanitization + Gear Popover
        row_san = layout.row(align=True)
        row_san.use_property_split = False
        row_san.scale_y = 1.25
        row_san.operator("lod_tool.clean_and_repair_mesh", text="Sanitize Base Mesh", icon="BRUSH_DATA")
        row_san.popover(panel="OMNIMESH_PT_popover_sanitize", icon="PREFERENCES", text="")

        # 2. Action Row 2: Material Cleanup + Gear Popover
        row_mat = layout.row(align=True)
        row_mat.use_property_split = False
        row_mat.scale_y = 1.25
        row_mat.operator("lod_tool.clean_and_repair_materials", text="Clean Materials", icon="MATERIAL_DATA")
        row_mat.popover(panel="OMNIMESH_PT_popover_materials", icon="PREFERENCES", text="")

        # 3. Action Row 3: Collision Hulls + Delete + Gear Popover
        row_col = layout.row(align=True)
        row_col.use_property_split = False
        row_col.scale_y = 1.25
        row_col.operator("lod_tool.generate_collision_hulls", text="Generate Colliders", icon="MOD_PHYSICS")

        # Determine if colliders exist for the active asset base collection
        base_name = resolve_effective_asset_name(context, props)
        coll_name = f"{base_name}_Colliders" if base_name else ""
        collider_count = 0
        if bpy and hasattr(bpy, "data") and hasattr(bpy.data, "collections") and coll_name:
            target_coll = bpy.data.collections.get(coll_name)
            if target_coll and hasattr(target_coll, "objects"):
                collider_count = len(
                    [o for o in target_coll.objects if o.get("_is_collider", False) or "_Collider_" in o.name]
                )
        last_count = getattr(props, "last_generated_collider_count", 0)
        if collider_count == 0 and isinstance(last_count, int) and last_count > 0:
            collider_count = last_count

        sub_del = row_col.row(align=True)
        sub_del.enabled = collider_count > 0
        sub_del.operator("lod_tool.remove_collision_hulls", text="", icon="X")
        row_col.popover(panel="OMNIMESH_PT_popover_collision", icon="PREFERENCES", text="")


# =========================================================================
# PANEL 3: LODs (Configuration, UIList, Decimation & Testing)
# =========================================================================


class OMNIMESH_PT_lods(Panel):
    """Panel 3: LOD Generation Pipeline and Responsive UIList Table."""

    bl_label = "3. LODs"
    bl_idname = "OMNIMESH_PT_lods"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OmniMesh"
    bl_order = 2

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props, _, _ = resolve_lod_context(context)
        if not props or (len(getattr(props, "lods", [])) == 0 and len(getattr(context.scene.lod_tool, "lods", [])) > 0):
            props = context.scene.lod_tool

        # Contextual Selection & Hierarchy Banners
        sel_meshes = [o for o in context.selected_objects if o.type == "MESH"]
        if len(sel_meshes) > 1:
            row_sync = layout.row(align=True)
            row_sync.operator(
                "lod_tool.sync_selection_settings",
                text=f"Sync Settings to Selection ({len(sel_meshes)} meshes)",
                icon="COMMUNITY",
            )

        active_obj = context.active_object
        if active_obj and hasattr(active_obj, "lod_tool"):
            root_val = active_obj.lod_tool.lod_root_object
            if root_val and (getattr(active_obj.lod_tool, "is_generated_lod", False) or "_LOD" in active_obj.name):
                root_name = root_val.name if hasattr(root_val, "name") else str(root_val)
                row_nav = layout.row(align=True)
                row_nav.label(text=f"Sub-LOD of '{root_name}'", icon="LINKED")
                row_nav.operator("lod_tool.select_master_asset", text="Select Master", icon="RESTRICT_SELECT_OFF")

        # Selection vs Configured Asset mismatch alert
        if active_obj and props.export_base_name:
            curr_base = active_obj.name.split("_LOD")[0]
            if curr_base != props.export_base_name:
                box_alert = layout.box()
                box_alert.alert = True
                box_alert.label(
                    text=f"Selected: '{curr_base}' (Configured: '{props.export_base_name}')",
                    icon="INFO",
                )

        box_lod = layout.box()
        box_lod.label(text="LOD Generation & Progression", icon="GEOMETRY_NODES")

        # Row 0: Asset Selection & Discovery
        row_asset = box_lod.row(align=True)
        row_asset.use_property_split = False
        row_asset.prop(props, "active_asset", text="Asset")

        # Row 1: [ Preset Dropdown ▾ ] [ ↺ Reset ] [ 📋 Copy ] [ ❌ Delete ] [ ⚙️ Gear ]
        raw_preset = getattr(props, "lod_preset", "")
        preset_id = str(raw_preset).strip() or DEFAULT_LOD_PRESET_ID

        row_preset = box_lod.row(align=True)
        row_preset.use_property_split = False
        row_preset.prop(props, "lod_preset", text="Preset")
        row_preset.operator("lod_tool.reset_to_preset", text="", icon="FILE_REFRESH")
        op_dup_lod = row_preset.operator("lod_tool.duplicate_preset", text="", icon="DUPLICATE")
        op_dup_lod.preset_type = "LOD"

        sub_del = row_preset.row(align=True)
        sub_del.enabled = LODPresetManager.is_user_preset(preset_id)
        sub_del.operator("lod_tool.delete_lod_preset", text="", icon="X")
        row_preset.popover(panel="OMNIMESH_PT_popover_lod_preset", icon="PREFERENCES", text="")

        # Visual Stability (tau_sse) slider directly below preset
        box_lod.prop(props, "tau_sse", text="Visual Stability (τ_sse)", slider=True)

        base_tris = getattr(props, "base_triangles", 0) or getattr(props, "last_generated_base_tris", 0)
        if base_tris <= 0:
            effective_asset = resolve_effective_asset_name(context, props)
            l0_meshes = get_asset_base_meshes(context, effective_asset) if effective_asset else []
            if l0_meshes:
                base_tris = sum(
                    sum(len(p.vertices) - 2 for p in m.data.polygons)
                    for m in l0_meshes
                    if hasattr(m, "data") and hasattr(m.data, "polygons")
                )
            elif (
                active_obj
                and getattr(active_obj, "type", "") == "MESH"
                and hasattr(active_obj, "data")
                and hasattr(active_obj.data, "polygons")
            ):
                base_tris = sum(len(p.vertices) - 2 for p in active_obj.data.polygons)

        has_out_of_sync = False

        # LOD Tiers rendered as clean, full-width Cards
        if props.lods:
            for idx, tier in enumerate(props.lods):
                card = box_lod.box()
                card.use_property_split = False

                # Card Header: [👁 Solo] Tier Name • Tris Count   [Badge]   [X Delete]
                row_hdr = card.row(align=True)
                is_solo = getattr(tier, "is_soloed", False)
                solo_icon = "HIDE_OFF" if is_solo else "HIDE_ON"
                op_s = row_hdr.operator("lod_tool.solo_tier", text="", icon=solo_icon, emboss=False)
                op_s.tier_index = idx

                tier_name = getattr(tier, "name", f"LOD{idx}")
                actual_t = getattr(tier, "actual_tris", 0)

                # Determine card state badge
                state = getattr(tier, "state", "PLANNED")
                last_target = getattr(tier, "last_baked_target_pct", -1.0)
                if idx == 0:
                    state = "SOURCE"
                elif last_target > 0.0 and abs(tier.target_tris_pct - last_target) > 0.01:
                    state = "OUT_OF_SYNC"
                    has_out_of_sync = True
                elif actual_t > 0:
                    state = "BAKED"
                else:
                    state = "PLANNED"

                if getattr(tier, "is_impostor", False):
                    row_hdr.label(text=f"{tier_name} (Impostor)", icon="IMAGE_DATA")
                elif actual_t > 0:
                    row_hdr.label(text=f"{tier_name}  •  {actual_t:,} tris", icon="MESH_DATA")
                else:
                    row_hdr.label(text=f"{tier_name}", icon="MESH_DATA")

                # State Badge
                if state == "SOURCE":
                    row_hdr.label(text="Source")
                elif state == "BAKED":
                    row_hdr.label(text="Baked")
                elif state == "OUT_OF_SYNC":
                    row_hdr.label(text="Out of Sync")
                else:
                    row_hdr.label(text="Planned")

                if idx > 0 and len(props.lods) > 1:
                    op_del = row_hdr.operator("lod_tool.remove_lod_tier", text="", icon="X", emboss=False)
                    op_del.tier_index = idx

                # Sliders: LOD0 is read-only baseline; LOD1..k have full-width interactive sliders
                if idx > 0:
                    target_calc = (
                        int(base_tris * (tier.target_tris_pct / 100.0))
                        if base_tris > 0
                        else getattr(tier, "target_tris", 0)
                    )
                    row_pct = card.row()
                    row_pct.prop(
                        tier,
                        "target_tris_pct",
                        text=f"Tris: {tier.target_tris_pct:.0f}%  (~{target_calc:,})",
                        slider=True,
                    )

                    row_dist = card.row()
                    dist_text = f"  ({tier.distance_m:.1f}m)" if tier.distance_m > 0 else ""
                    row_dist.prop(
                        tier,
                        "screen_size_pct",
                        text=f"Screen: {tier.screen_size_pct:.0f}%{dist_text}",
                        slider=True,
                    )

            # Cull Screen Size directly below the final LOD card (completes visibility lifecycle)
            row_cull = box_lod.row(align=True)
            row_cull.prop(props, "cull_screen_size_pct", text="Cull at Screen Size", slider=True)

            row_add = box_lod.row(align=True)
            row_add.operator("lod_tool.add_lod_tier", text="Add LOD Tier", icon="ADD")
        else:
            box_info = box_lod.box()
            box_info.label(text="No LOD tiers projected.", icon="INFO")
            box_info.operator("lod_tool.reset_to_preset", text="Project From Preset", icon="FILE_REFRESH")

        # Single Prominent Action Button at Bottom of Panel 3
        col_act = box_lod.column(align=True)
        col_act.use_property_split = False
        col_act.scale_y = 1.35
        action_text = "Update Out-of-Sync LODs" if has_out_of_sync else "Generate All LODs"
        op_gen = col_act.operator("lod_tool.generate_all", text=action_text, icon="GEOMETRY_NODES")
        op_gen.only_out_of_sync = has_out_of_sync


class OMNIMESH_PT_lods_testing(Panel):
    """Subpanel: Testing & Viewport Inspection Tools."""

    bl_label = "Testing & Inspection"
    bl_idname = "OMNIMESH_PT_lods_testing"
    bl_parent_id = "OMNIMESH_PT_lods"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OmniMesh"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        row_test = layout.row(align=True)
        row_test.use_property_split = False
        row_test.scale_y = 1.15
        if props.is_simulator_running:
            row_test.operator("lod_tool.toggle_simulator", text="Stop Simulator", icon="CANCEL")
        else:
            row_test.operator("lod_tool.toggle_simulator", text="Live Simulator", icon="PLAY")

        if props.is_split_active:
            row_test.operator("lod_tool.toggle_split_preview", text="Exit Split", icon="CANCEL")
        else:
            row_test.operator("lod_tool.toggle_split_preview", text="A/B Split", icon="UV_SYNC_SELECT")

        # Dynamic A/B Split Controls
        if props.is_split_active:
            box_split = layout.box()
            box_split.use_property_split = True
            box_split.use_property_decorate = False
            box_split.prop(props, "split_compare_tier", text="Compare Tier")
            box_split.prop(props, "split_ratio", text="Split Ratio", slider=True)

        # Virtual Distance Override & HUD Toggle
        row_sweep = layout.row(align=True)
        row_sweep.use_property_split = False
        row_sweep.prop(props, "virtual_distance_override", text="Virtual Dist (m)", slider=True)
        row_sweep.prop(props, "show_viewport_hud", text="", icon="WINDOW")


# =========================================================================
# PANEL 4: ENGINE EXPORT (Package Export, Textures, Bridge & Batch)
# =========================================================================


class OMNIMESH_PT_export(Panel):
    """Panel 4: Single Asset Multi-Engine Export, PBR Texture Channel Packing & Live Bridge."""

    bl_label = "4. Engine Export"
    bl_idname = "OMNIMESH_PT_export"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OmniMesh"
    bl_order = 3

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        box_exp = layout.box()
        box_exp.label(text="Package Export", icon="EXPORT")

        # Row 1: [ Preset Dropdown ▾ ] [ 📋 Copy ] [ ❌ Delete ] [ ⚙️ Gear ]
        raw_exp = str(getattr(props, "pbr_export_preset", "")).strip() or str(getattr(props, "pbr_preset", "")).strip()
        export_preset_id = raw_exp or DEFAULT_PRESET_ID
        is_builtin_exp = PBRExportPresetManager.is_builtin(export_preset_id)

        row_preset = box_exp.row(align=True)
        row_preset.use_property_split = False
        row_preset.prop(props, "pbr_export_preset", text="Preset")
        op_dup_exp = row_preset.operator("lod_tool.duplicate_preset", text="", icon="DUPLICATE")
        op_dup_exp.preset_type = "EXPORT"

        sub_del_exp = row_preset.row(align=True)
        sub_del_exp.enabled = not is_builtin_exp
        sub_del_exp.operator("lod_tool.delete_export_preset", text="", icon="X")
        row_preset.popover(panel="OMNIMESH_PT_popover_export_preset", icon="PREFERENCES", text="")

        # Row 2: Batch Mode Toggle
        row_batch = box_exp.row(align=True)
        row_batch.use_property_split = False
        row_batch.prop(props, "batch_mode", text="Batch Export (.blend files)")

        if getattr(props, "batch_mode", False):
            row_src = box_exp.row(align=True)
            row_src.use_property_split = False
            row_src.prop(props, "batch_source_directory", text="Source")

            row_act = box_exp.row(align=True)
            row_act.use_property_split = False
            row_act.scale_y = 1.15
            if getattr(props, "is_batch_running", False):
                row_act.operator("lod_tool.batch_cancel", text="Cancel Batch", icon="CANCEL")
            else:
                row_act.operator("lod_tool.batch_process", text="Batch Export", icon="PACKAGE")
            row_act.prop(props, "export_directory", text="")

            if getattr(props, "is_batch_running", False):
                box_status = box_exp.box()
                box_status.label(text=props.batch_status_text, icon="TIME")
        else:
            row2_exp = box_exp.row(align=True)
            row2_exp.use_property_split = False
            row2_exp.scale_y = 1.15
            row2_exp.operator("lod_tool.export_engine_package", text="Export", icon="PACKAGE")
            row2_exp.prop(props, "export_directory", text="")

        # Row 3: Live Link Status / Toggle
        row3_link = box_exp.row(align=True)
        row3_link.use_property_split = False
        row3_link.scale_y = 1.1
        if not props.enable_live_sync:
            row3_link.alert = False
            row3_link.operator("lod_tool.toggle_live_bridge", text="Live Link: Off", icon="RADIOBUT_OFF")
        elif props.bridge_connected:
            row3_link.alert = False
            row3_link.operator("lod_tool.toggle_live_bridge", text="Live Link: Active", icon="COLOR_GREEN")
        else:
            row3_link.alert = True
            row3_link.operator("lod_tool.toggle_live_bridge", text="Live Link: Offline", icon="COLOR_RED")


# Strict Parent-First Topological Registration Order
PRIMARY_PANELS = (
    OMNIMESH_PT_import,
    OMNIMESH_PT_modify,
    OMNIMESH_PT_lods,
    OMNIMESH_PT_export,
)

SUBPANEL_CLASSES = (OMNIMESH_PT_lods_testing,)

PANEL_CLASSES = PRIMARY_PANELS + SUBPANEL_CLASSES + POPOVER_CLASSES


def register_panel() -> None:
    if not bpy:
        return
    for cls in PANEL_CLASSES:
        existing = getattr(bpy.types, cls.__name__, None)
        if existing is not None:
            try:
                bpy.utils.unregister_class(existing)
            except Exception as exc:
                logger.debug("Safe unregister skipped %s: %s", cls.__name__, exc)
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            logger.warning("Could not register %s: %s", cls.__name__, exc)


def unregister_panel() -> None:
    if not bpy:
        return
    for cls in reversed(PANEL_CLASSES):
        bpy.utils.unregister_class(cls)
