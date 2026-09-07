"""
OmniMesh Modular Panel Architecture for Blender 4.2+ and 5.2 LTS.
Structured into four streamlined sequential workflow panels with gear-icon popovers:
1. Import (PBR Texture Set Importer & Auto-Matcher)
2. Modify (Base Mesh Preflight, Sanitization, Modifiers, and Material Cleanup)
3. LODs (Tier Configuration, UIList, Decimation, Isolate, Simulator & Preview)
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
    from ..core.pbr_presets import (
        DEFAULT_PRESET_ID,
        PBRExportPresetManager,
        PBRImportPresetManager,
    )
    from .operators import get_selected_mesh_objects
    from .popovers import POPOVER_CLASSES
except (ImportError, ValueError):
    from core.pbr_presets import (
        DEFAULT_PRESET_ID,
        PBRExportPresetManager,
        PBRImportPresetManager,
    )
    from ui.operators import get_selected_mesh_objects
    from ui.popovers import POPOVER_CLASSES


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
        row_preset.prop(props, "pbr_import_preset", text="Preset")
        op_dup_imp = row_preset.operator("lod_tool.duplicate_preset", text="", icon="DUPLICATE")
        op_dup_imp.preset_type = "IMPORT"

        sub_del = row_preset.row(align=True)
        sub_del.enabled = not is_builtin
        sub_del.operator("lod_tool.delete_import_preset", text="", icon="X")
        row_preset.popover(panel="OMNIMESH_PT_popover_import_preset", icon="PREFERENCES", text="")

        # Row 2: [ Import ] [ Path Field ][ 📁 ]
        row2 = box_pbr.row(align=True)
        row2.scale_y = 1.15
        row2.operator("lod_tool.import_pbr_set", text="Import", icon="IMPORT")
        row2.prop(props, "pbr_import_directory", text="")

        if props.last_pbr_import_summary:
            box_pbr.label(text=props.last_pbr_import_summary, icon="CHECKMARK")


# =========================================================================
# PANEL 2: MODIFY (Base Prep, Health, Sanitization & Materials)
# =========================================================================


class OMNIMESH_PT_modify(Panel):
    """Panel 2: Base Mesh Preflight Inspection, Sanitization, Modifiers, and Material Cleanup."""

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

        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            box = layout.box()
            box.label(text="No Mesh Selected", icon="INFO")
            box.label(text="Select an active mesh object to inspect.")
            return

        # 1. Compact Preflight Health Card
        box_pre = layout.box()
        row_pre = box_pre.row(align=True)
        row_pre.label(text="LOD0 Health Check", icon="MESH_DATA")
        row_pre.operator("lod_tool.inspect_lod0", text="Run Preflight", icon="VIEWZOOM")

        if props.preflight_inspected:
            col_stat = box_pre.column(align=True)
            if props.preflight_is_clean:
                col_stat.label(text=props.preflight_summary_text, icon="CHECKMARK")
            else:
                col_stat.label(text=props.preflight_summary_text, icon="ERROR")

            # Compact Metrics Breakdown
            row_b = box_pre.row(align=True)
            scale_icon = "CHECKMARK" if not props.preflight_unapplied_scale else "CANCEL"
            row_b.label(text="Scale: 1.0", icon=scale_icon)
            loose_icon = "CHECKMARK" if props.preflight_loose_verts == 0 else "CANCEL"
            row_b.label(text=f"Loose: {props.preflight_loose_verts}", icon=loose_icon)
            deg_icon = "CHECKMARK" if props.preflight_degenerate_tris == 0 else "CANCEL"
            row_b.label(text=f"Deg: {props.preflight_degenerate_tris}", icon=deg_icon)
            mat_icon = "CHECKMARK" if props.preflight_missing_materials == 0 else "CANCEL"
            row_b.label(text=f"Mat: {props.preflight_missing_materials}", icon=mat_icon)

        # 2. Action Row 1: Mesh Sanitization + Gear Popover
        row_san = layout.row(align=True)
        row_san.scale_y = 1.3
        row_san.operator("lod_tool.clean_and_repair_mesh", text="🧹 Sanitize Base Mesh", icon="BRUSH_DATA")
        row_san.popover(panel="OMNIMESH_PT_popover_sanitize", icon="PREFERENCES", text="")

        # 3. Action Row 2: Material Cleanup + Gear Popover
        row_mat = layout.row(align=True)
        row_mat.scale_y = 1.25
        row_mat.operator("lod_tool.clean_and_repair_materials", text="🎨 Clean Materials", icon="MATERIAL_DATA")
        row_mat.popover(panel="OMNIMESH_PT_popover_materials", icon="PREFERENCES", text="")

        if props.last_material_cleanup_summary:
            box_stat = layout.box()
            box_stat.label(text=props.last_material_cleanup_summary, icon="CHECKMARK")


# =========================================================================
# PANEL 3: LODs (Configuration, QEM Decimation, Viewport Tools & Simulator)
# =========================================================================


class OMNIMESH_PT_lods(Panel):
    """Panel 3: LOD Generation Pipeline, UIList Table, Viewport Isolation, and Simulator."""

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
        props = context.scene.lod_tool

        # Selection vs Configured Asset mismatch alert
        active_obj = context.active_object
        if active_obj and props.export_base_name:
            curr_base = active_obj.name.split("_LOD")[0]
            if curr_base != props.export_base_name:
                box_alert = layout.box()
                box_alert.alert = True
                box_alert.label(
                    text=f"Selected: '{curr_base}' (Configured: '{props.export_base_name}')",
                    icon="INFO",
                )

        # 1. Preset & Configuration Row + Gear Popover
        box_cfg = layout.box()
        row_cfg_head = box_cfg.row(align=True)
        target_item = props.bl_rna.properties["target_engine"].enum_items.get(props.target_engine)
        target_label = target_item.name if target_item else str(props.target_engine)
        row_cfg_head.label(text=f"Target: {target_label.split(' (')[0]} | {props.asset_category}", icon="SCENE_DATA")

        row_cfg = box_cfg.row(align=True)
        row_cfg.scale_y = 1.25
        row_cfg.operator("lod_tool.analyze_and_configure", text="1. Auto-Configure Tiers", icon="VIEWZOOM")
        row_cfg.popover(panel="OMNIMESH_PT_popover_configure", icon="PREFERENCES", text="")

        if props.lods:
            # UIList Table
            box_list = layout.box()
            box_list.template_list(
                "LOD_UL_tier_list", "", props, "lods", props, "active_lod_index", rows=min(6, len(props.lods))
            )

            # Selected Tier Detail
            active_idx = max(0, min(props.active_lod_index, len(props.lods) - 1))
            active_tier = props.lods[active_idx]
            box_detail = layout.box()
            row_det = box_detail.row(align=True)
            row_det.label(text=f"{active_tier.name} Switch: {active_tier.distance_m:.1f}m", icon="CON_DISTLIMIT")
            row_det.label(text=f"Slots: {active_tier.mat_slots_count}", icon="MATERIAL")

            # 2. Primary Action CTA: Generate All LODs + Gear Popover
            row_gen = layout.row(align=True)
            row_gen.scale_y = 1.35
            row_gen.operator("lod_tool.generate_all", text="2. Generate All LODs", icon="GEOMETRY_NODES")
            row_gen.popover(panel="OMNIMESH_PT_popover_generate", icon="PREFERENCES", text="")

            # Post-Generation Summary Banner
            if props.last_generated_tier_count > 0 and props.last_generated_base_tris > 0:
                box_summary = layout.box()
                box_summary.label(
                    text=f"✔ {props.last_generated_tier_count} LODs: {props.last_generated_base_tris:,} → {props.last_generated_final_tris:,} tris (-{props.last_generated_reduction_pct:.1f}%)",
                    icon="CHECKMARK",
                )

            # Isolate Viewport LOD Grid Flow
            box_iso = layout.box()
            box_iso.label(text="Isolate Viewport LOD", icon="HIDE_OFF")
            grid = box_iso.grid_flow(row_major=True, columns=0, even_columns=True, align=True)
            for i in range(len(props.lods)):
                op = grid.operator("lod_tool.preview_tier", text=f"LOD{i}")
                op.tier_index = i


class OMNIMESH_PT_inspection_sub(Panel):
    """Subpanel 3.1: Viewport Inspection, Real-Time LOD Simulator & A/B Split Preview."""

    bl_label = "Viewport Inspection & Simulator"
    bl_idname = "OMNIMESH_PT_inspection_sub"
    bl_parent_id = "OMNIMESH_PT_lods"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OmniMesh"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 0

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        # Real-Time LOD Simulator
        box_sim = layout.box()
        box_sim.label(text="Real-Time Viewport Simulator", icon="PLAY")
        row = box_sim.row(align=True)
        row.scale_y = 1.2
        if props.is_simulator_running:
            row.operator("lod_tool.toggle_live_simulator", text="Stop Simulation", icon="CANCEL")
        else:
            row.operator("lod_tool.toggle_live_simulator", text="Start Live Simulator", icon="PLAY")

        box_sim.prop(props, "simulator_mode", text="Mode")
        if props.simulator_mode == "VIRTUAL_SLIDER":
            box_sim.prop(props, "virtual_screen_size_pct", slider=True)
            box_sim.prop(props, "virtual_preview_dist_m")

        # A/B Split-Screen Viewport Comparison
        box_split = layout.box()
        box_split.label(text="A/B Split-Screen Comparison", icon="UV_SYNC_SELECT")
        row = box_split.row(align=True)
        row.scale_y = 1.2
        if props.is_split_active:
            row.operator("lod_tool.toggle_split_preview", text="Exit Split Preview", icon="CANCEL")
            box_split.prop(props, "split_ratio", text="Split Line", slider=True)
            box_split.prop(props, "split_compare_tier", text="Compare Tier")
        else:
            row.operator("lod_tool.toggle_split_preview", text="Start Split Preview", icon="VIEW_CAMERA")
            box_split.prop(props, "split_compare_tier", text="Compare Tier")

        # Viewport HUD Toggle
        box_hud = layout.box()
        box_hud.prop(props, "show_viewport_hud", text="Show Viewport HUD Overlay", icon="WINDOW")


# =========================================================================
# PANEL 4: ENGINE EXPORT (Multi-Engine Package, Textures, Bridge & Batch)
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

        # Single Asset Package Export
        box_exp = layout.box()
        box_exp.label(text="Package Export", icon="EXPORT")

        # Row 1: [ Preset Dropdown ▾ ] [ 📋 Copy ] [ ❌ Delete ] [ ⚙️ Gear ]
        raw_exp = str(getattr(props, "pbr_export_preset", "")).strip() or str(getattr(props, "pbr_preset", "")).strip()
        export_preset_id = raw_exp or DEFAULT_PRESET_ID
        is_builtin_exp = PBRExportPresetManager.is_builtin(export_preset_id)

        row_preset = box_exp.row(align=True)
        row_preset.prop(props, "pbr_export_preset", text="Preset")
        op_dup_exp = row_preset.operator("lod_tool.duplicate_preset", text="", icon="DUPLICATE")
        op_dup_exp.preset_type = "EXPORT"

        sub_del_exp = row_preset.row(align=True)
        sub_del_exp.enabled = not is_builtin_exp
        sub_del_exp.operator("lod_tool.delete_export_preset", text="", icon="X")
        row_preset.popover(panel="OMNIMESH_PT_popover_export_preset", icon="PREFERENCES", text="")

        # Row 2: Batch Mode Toggle (Checkbox)
        row_batch = box_exp.row(align=True)
        row_batch.prop(props, "batch_mode", text="Batch Export (.blend files)")

        if getattr(props, "batch_mode", False):
            # Source Folder Field
            row_src = box_exp.row(align=True)
            row_src.prop(props, "batch_source_directory", text="Source")

            # Batch Export Action + Destination Path
            row_act = box_exp.row(align=True)
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
            # Single Asset Export Action + Destination Path
            row2_exp = box_exp.row(align=True)
            row2_exp.scale_y = 1.15
            row2_exp.operator("lod_tool.export_engine_package", text="Export", icon="PACKAGE")
            row2_exp.prop(props, "export_directory", text="")

        # Row 3: Live Link Status / Toggle (Positioned under Export)
        row3_link = box_exp.row(align=True)
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

SUBPANEL_CLASSES = (OMNIMESH_PT_inspection_sub,)

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
