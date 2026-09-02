"""
OmniMesh 3-Panel Architecture for Blender 4.2+ and 5.2 LTS.
Structured into three primary sequential workflow panels:
1. Fix LOD0 (Sanitize, Repair, Transform & Origin Normalization)
2. LODs (Configure, Generate, Simulate, Split Preview & Isolate)
3. Engine Export (Multi-Engine Package Export, PBR Textures, Live Bridge & Batch Ingestion)
"""

from __future__ import annotations

from typing import Any

try:
    import bpy
    from bpy.types import Panel
except ImportError:
    bpy = None
    Panel = object

try:
    from .operators import get_associated_armature, get_selected_mesh_objects
except (ImportError, ValueError):
    from ui.operators import get_associated_armature, get_selected_mesh_objects


# =========================================================================
# PANEL 1: FIX LOD0 (Sanitization, Preflight & Geometry Normalization)
# =========================================================================


class OMNIMESH_PT_fix_lod0(Panel):
    """Panel 1: Base Mesh Preflight Inspection, Sanitization, and Transform Normalization."""

    bl_label = "1. Fix LOD0"
    bl_idname = "OMNIMESH_PT_fix_lod0"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OmniMesh"
    bl_order = 0

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

        # Preflight Health Card
        box_pre = layout.box()
        row = box_pre.row(align=True)
        row.label(text="LOD0 Health Check", icon="MESH_DATA")
        row.operator("lod_tool.inspect_lod0", text="Run Preflight", icon="VIEWZOOM")

        if props.preflight_inspected:
            col_stat = box_pre.column(align=True)
            if props.preflight_is_clean:
                col_stat.label(text=props.preflight_summary_text, icon="CHECKMARK")
            else:
                col_stat.label(text=props.preflight_summary_text, icon="ERROR")

            # Metrics Breakdown
            row_badges = box_pre.row(align=True)
            scale_icon = "CHECKMARK" if not props.preflight_unapplied_scale else "CANCEL"
            row_badges.label(text="Scale: 1.0", icon=scale_icon)
            loose_icon = "CHECKMARK" if props.preflight_loose_verts == 0 else "CANCEL"
            row_badges.label(text=f"Loose: {props.preflight_loose_verts}", icon=loose_icon)

            row_badges2 = box_pre.row(align=True)
            deg_icon = "CHECKMARK" if props.preflight_degenerate_tris == 0 else "CANCEL"
            row_badges2.label(text=f"Degenerates: {props.preflight_degenerate_tris}", icon=deg_icon)
            mat_icon = "CHECKMARK" if props.preflight_missing_materials == 0 else "CANCEL"
            row_badges2.label(text=f"Missing Mat: {props.preflight_missing_materials}", icon=mat_icon)

        # Primary Sanitization Action
        col_act = layout.column(align=True)
        col_act.scale_y = 1.3
        col_act.operator("lod_tool.sanitize_base_mesh", text="🧹 Sanitize & Fix Base Mesh", icon="BRUSH_DATA")

        # Transform Normalization Action
        col_trans = layout.column(align=True)
        col_trans.scale_y = 1.15
        col_trans.operator("lod_tool.apply_transforms", text="Apply Scale & Rotation", icon="OBJECT_ORIGIN")

        # Tuning Parameters
        box_opt = layout.box()
        box_opt.label(text="Sanitizer Tuning", icon="PREFERENCES")
        box_opt.prop(props, "sanitize_merge_epsilon", text="Merge Epsilon", slider=True)


# =========================================================================
# PANEL 2: LODs (Configuration, QEM Decimation, Viewport Tools & Inspection)
# =========================================================================


class OMNIMESH_PT_lods(Panel):
    """Panel 2: LOD Generation Pipeline, UIList Table, and Viewport Isolation."""

    bl_label = "2. LODs"
    bl_idname = "OMNIMESH_PT_lods"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OmniMesh"
    bl_order = 1

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

        # 1. Preset & Target Setup
        box = layout.box()
        box.label(text="Target Engine & Asset Role", icon="SCENE_DATA")
        box.prop(props, "target_engine", text="")
        box.prop(props, "asset_category", text="")
        box.prop(props, "export_base_name", text="Asset Name")

        # 2. Quality & Tolerances
        box_q = layout.box()
        box_q.label(text="Quality & Screen Error", icon="RESTRICT_VIEW_OFF")
        box_q.prop(props, "tau_sse", slider=True, text="Visual Stability (SSE)")
        box_q.prop(props, "cull_screen_size_pct", slider=True, text="Cull Screen Size (%)")
        if props.target_engine != "MSFS_2024":
            box_q.prop(props, "num_lods", text="LOD Tier Count")

        # Step 1 CTA: Auto-Configure
        col_cta = layout.column(align=True)
        col_cta.scale_y = 1.3
        col_cta.operator("lod_tool.analyze_and_configure", text="1. Auto-Configure Tiers", icon="VIEWZOOM")

        if props.lods:
            # UIList Table
            box_list = layout.box()
            box_list.template_list(
                "LOD_UL_tier_list", "", props, "lods", props, "active_lod_index", rows=len(props.lods)
            )

            # Selected Tier Detail
            active_idx = max(0, min(props.active_lod_index, len(props.lods) - 1))
            active_tier = props.lods[active_idx]
            box_detail = layout.box()
            row = box_detail.row(align=True)
            row.label(text=f"{active_tier.name} Switch: {active_tier.distance_m:.1f}m", icon="CON_DISTLIMIT")
            row.label(text=f"Slots: {active_tier.mat_slots_count}", icon="MATERIAL")

            # Step 2 Primary Action CTA
            col_gen = layout.column(align=True)
            col_gen.scale_y = 1.35
            col_gen.operator("lod_tool.generate_all", text="2. Generate All LODs", icon="GEOMETRY_NODES")

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
    """Subpanel 2.1: Viewport Inspection, Real-Time LOD Simulator & A/B Split Preview."""

    bl_label = "Viewport Inspection & Simulator"
    bl_idname = "OMNIMESH_PT_inspection_sub"
    bl_parent_id = "OMNIMESH_PT_lods"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
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


class OMNIMESH_PT_optimization_sub(Panel):
    """Subpanel 2.2: Hierarchy Draw-Call Merging, Rigging Kinematics & PBR Texture Baking."""

    bl_label = "Advanced Optimization & Rigging"
    bl_idname = "OMNIMESH_PT_optimization_sub"
    bl_parent_id = "OMNIMESH_PT_lods"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 1

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool
        mesh_objs = get_selected_mesh_objects(context)
        armature_obj = get_associated_armature(mesh_objs)

        # Hierarchy & Draw-Call Optimization
        box_h = layout.box()
        box_h.label(text="Draw-Call Merging", icon="OUTLINER_OB_GROUP_INSTANCE")
        box_h.prop(props, "hierarchy_mode", text="")
        if props.hierarchy_mode == "MERGE_AT_TIER":
            box_h.prop(props, "merge_start_tier")
        box_h.prop(props, "preserve_slot_indexing")

        # Rigging & Skeletal Kinematics
        box_r = layout.box()
        box_r.label(text="Rigging & Skeletal Kinematics", icon="ARMATURE_DATA")
        has_skinning = bool(armature_obj or any(len(obj.vertex_groups) > 0 for obj in mesh_objs))
        if not has_skinning:
            box_r.label(text="No Armature or Deform Groups Detected", icon="INFO")
        col_rig = box_r.column()
        col_rig.active = has_skinning
        col_rig.prop(props, "max_bone_influences")
        col_rig.prop(props, "enable_bone_pruning")
        col_rig.prop(props, "purge_shape_keys")


# =========================================================================
# PANEL 3: ENGINE EXPORT (Multi-Engine Package, Textures, Bridge & Batch)
# =========================================================================


class OMNIMESH_PT_export(Panel):
    """Panel 3: Single Asset Multi-Engine Export, PBR Texture Channel Packing & Live Bridge."""

    bl_label = "3. Engine Export"
    bl_idname = "OMNIMESH_PT_export"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OmniMesh"
    bl_order = 2

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        # Single Asset Package Export
        box_exp = layout.box()
        box_exp.label(text="Package Export", icon="EXPORT")
        box_exp.prop(props, "export_directory", text="Output Dir")
        col_exp = box_exp.column(align=True)
        col_exp.scale_y = 1.25
        col_exp.operator("lod_tool.export_engine_package", text="Export Engine Package", icon="PACKAGE")

        # PBR Texture Channel Packing & Animation
        box_tex = layout.box()
        box_tex.label(text="PBR Textures & Rig Animations", icon="NODE_MATERIAL")
        box_tex.prop(props, "export_packed_textures")
        if props.export_packed_textures:
            box_tex.prop(props, "texture_max_resolution")
            box_tex.operator("lod_tool.pack_pbr_textures", icon="IMAGE_DATA")
        box_tex.prop(props, "bake_animations")
        if props.bake_animations:
            box_tex.operator("lod_tool.bake_rig_animation", icon="ACTION")

        # Live Engine Bridge
        box_br = layout.box()
        box_br.label(text="⚡ Live Engine Bridge", icon="LINKED")
        box_br.prop(props, "engine_project_path", text="Project Path")
        box_br.prop(props, "enable_live_sync", text="Auto-Sync on Export")

        # Display cached status string (zero blocking I/O)
        box_br.label(
            text=props.bridge_status_text,
            icon="RADIOBUT_ON"
            if "Connected" in props.bridge_status_text or "Ready" in props.bridge_status_text
            else "RADIOBUT_OFF",
        )

        row = box_br.row(align=True)
        row.scale_y = 1.2
        row.operator("lod_tool.sync_live_bridge", text="Sync to Engine", icon="FILE_REFRESH")


class OMNIMESH_PT_batch_sub(Panel):
    """Subpanel 3.1: Batch Asset Library Ingestion."""

    bl_label = "Batch Library Ingestion"
    bl_idname = "OMNIMESH_PT_batch_sub"
    bl_parent_id = "OMNIMESH_PT_export"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 0

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        box = layout.box()
        box.label(text="Batch Library Ingest", icon="FILE_FOLDER")
        box.prop(props, "batch_source_directory", text="Source Folder")
        box.prop(props, "batch_export_directory", text="Output Folder")
        box.prop(props, "batch_recursive_scan", text="Recursive Scan")

        row = box.row(align=True)
        row.scale_y = 1.2
        if props.is_batch_running:
            row.label(text=props.batch_status_text, icon="TIME")
        else:
            row.operator("lod_tool.batch_process", text="Batch Process Library", icon="AUTO")
            box.label(text=props.batch_status_text)


# Strict Parent-First Topological Registration Order
PANEL_CLASSES = (
    OMNIMESH_PT_fix_lod0,
    OMNIMESH_PT_lods,
    OMNIMESH_PT_inspection_sub,
    OMNIMESH_PT_optimization_sub,
    OMNIMESH_PT_export,
    OMNIMESH_PT_batch_sub,
)


def register_panel() -> None:
    if not bpy:
        return
    for cls in PANEL_CLASSES:
        bpy.utils.register_class(cls)


def unregister_panel() -> None:
    if not bpy:
        return
    for cls in reversed(PANEL_CLASSES):
        bpy.utils.unregister_class(cls)
