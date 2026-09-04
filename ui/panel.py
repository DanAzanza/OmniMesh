"""
OmniMesh Modular Panel Architecture for Blender 4.2+ and 5.2 LTS.
Structured into sequential workflow panels:
1. Import (PBR Texture Set Importer & Auto-Matcher)
2. Fix LOD0 (Sanitize, Preflight, Mesh Topology, Material Cleanup)
3. LODs (Configure, Generate, Simulate, Split Preview & Isolate)
4. Engine Export (Multi-Engine Package Export, PBR Textures, Live Bridge & Batch Ingestion)
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
    from .operators import get_associated_armature, get_selected_mesh_objects
except (ImportError, ValueError):
    from ui.operators import get_associated_armature, get_selected_mesh_objects


# =========================================================================
# PANEL 1: IMPORT (PBR Texture Set Importer & Folder Auto-Matcher)
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
        row_pbr = box_pbr.row(align=True)
        row_pbr.scale_y = 1.25
        row_pbr.operator("lod_tool.import_pbr_set", text="Import PBR Texture Set", icon="FILE_IMAGE")
        row_pbr.operator("lod_tool.auto_match_pbr_folder", text="Auto-Match Folder", icon="FILE_FOLDER")

        if props.last_pbr_import_summary:
            box_pbr.label(text=props.last_pbr_import_summary, icon="CHECKMARK")

        box_pbr.prop(props, "pbr_import_ao_mode", text="AO Routing")
        box_pbr.prop(props, "pbr_import_preserve_existing", text="Preserve Other Nodes")


# =========================================================================
# PANEL 2: FIX LOD0 (Sanitization, Preflight & Materials)
# =========================================================================


class OMNIMESH_PT_fix_lod0(Panel):
    """Panel 2: Base Mesh Preflight Inspection, Sanitization, and Material Cleanup."""

    bl_label = "2. Fix LOD0"
    bl_idname = "OMNIMESH_PT_fix_lod0"
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

        # 1. Preflight Health Card
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
        col_act.operator("lod_tool.clean_and_repair_mesh", text="Clean & Repair Mesh", icon="BRUSH_DATA")

        # Transform Normalization Action
        col_trans = layout.column(align=True)
        col_trans.scale_y = 1.15
        col_trans.operator("lod_tool.apply_transforms", text="Apply Scale & Rotation", icon="OBJECT_ORIGIN")
        col_trans.operator("lod_tool.apply_all_modifiers", text="Apply All Modifiers", icon="MODIFIER")

        # 2. Mesh Topology & Geometry Options
        box_mesh_opt = layout.box()
        box_mesh_opt.label(text="Mesh Topology & Cleanup Options", icon="PREFERENCES")
        box_mesh_opt.prop(props, "cleanup_apply_modifiers", text="Apply Modifiers (Bake Viewport)")
        if getattr(props, "cleanup_apply_modifiers", False):
            box_mesh_opt.prop(props, "cleanup_sync_viewport_settings", text="Sync Viewport to Render Settings")
        box_mesh_opt.prop(props, "cleanup_enable_split_non_manifold", text="Repair Non-Manifold & Bowties")
        box_mesh_opt.prop(props, "cleanup_normal_policy", text="Normals")

        row_w = box_mesh_opt.row(align=True)
        row_w.prop(props, "cleanup_enable_weld", text="Merge Close")
        if props.cleanup_enable_weld:
            row_w.prop(props, "cleanup_weld_distance", text="Dist")

        row_h = box_mesh_opt.row(align=True)
        row_h.prop(props, "cleanup_enable_fill_holes", text="Fill Holes")
        if props.cleanup_enable_fill_holes:
            row_h.prop(props, "cleanup_hole_max_edges", text="Max Edges")

        box_mesh_opt.prop(props, "cleanup_enable_triangulate_ngons", text="Triangulate N-Gons")

        # 3. Material Cleanup & Slot Consolidation Suite
        box_mat = layout.box()
        box_mat.label(text="Material Cleanup & Consolidation", icon="MATERIAL")
        row_mat = box_mat.row(align=True)
        row_mat.scale_y = 1.25
        row_mat.operator(
            "lod_tool.clean_and_repair_materials", text="Clean & Consolidate Materials", icon="MATERIAL_DATA"
        )

        if props.last_material_cleanup_summary:
            box_mat.label(text=props.last_material_cleanup_summary, icon="CHECKMARK")

        # Safe Material Toggles
        box_mat_safe = box_mat.box()
        box_mat_safe.label(text="Safe Operations (Default ON)", icon="CHECKMARK")
        box_mat_safe.prop(props, "mat_cleanup_purge_unused_slots")
        box_mat_safe.prop(props, "mat_cleanup_deduplicate_slots")
        box_mat_safe.prop(props, "mat_cleanup_merge_duplicate_datablocks")
        box_mat_safe.prop(props, "mat_cleanup_remove_orphan_nodes")

        # Critical Material Toggles
        box_mat_crit = box_mat.box()
        box_mat_crit.label(text="Critical Operations (Opt-In)", icon="ERROR")
        box_mat_crit.prop(props, "mat_cleanup_enable_micro_consolidation")
        if props.mat_cleanup_enable_micro_consolidation:
            box_mat_crit.prop(props, "mat_cleanup_micro_area_pct", text="Threshold %")
        box_mat_crit.prop(props, "mat_cleanup_repair_missing_textures")
        box_mat_crit.prop(props, "mat_cleanup_purge_orphans_blendfile")


# =========================================================================
# PANEL 3: LODs (Configuration, QEM Decimation, Viewport Tools & Inspection)
# =========================================================================


class OMNIMESH_PT_lods(Panel):
    """Panel 3: LOD Generation Pipeline, UIList Table, and Viewport Isolation."""

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
    """Subpanel 3.1: Viewport Inspection, Real-Time LOD Simulator & A/B Split Preview."""

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
    """Subpanel 3.2: Hierarchy Draw-Call Merging, Rigging Kinematics & PBR Texture Baking."""

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
    """Subpanel 4.1: Batch Asset Library Ingestion."""

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


class OMNIMESH_PT_chunking_sub(Panel):
    """Subpanel 3.3: Spatial Partitioning (Tiling), Seam Protection & HLOD Merging."""

    bl_label = "Spatial Chunking & HLOD (Large Assets)"
    bl_idname = "OMNIMESH_PT_chunking_sub"
    bl_parent_id = "OMNIMESH_PT_lods"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 2

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        box_pre = layout.box()
        box_pre.label(text="Raw Scan Surface Cleanup", icon="MOD_REMESH")
        box_pre.prop(props, "scan_remesh_voxel_size", text="Voxel Size")
        row_remesh = box_pre.row(align=True)
        row_remesh.operator("lod_tool.voxel_scan_cleanup", text="Pre-Process: Voxel Remesh", icon="SHADING_WIRE")

        box_chunk = layout.box()
        box_chunk.label(text="Spatial Chunking & Tiling", icon="GRID")
        box_chunk.prop(props, "chunk_partitioning_mode", text="Mode")
        if props.chunk_partitioning_mode == "ADAPTIVE_CLUSTERING":
            box_chunk.prop(props, "adaptive_cluster_target_polys", text="Target Poly Limit")
        box_chunk.prop(props, "chunk_cell_size", text="Cell Size (m)")
        box_chunk.prop(props, "chunk_split_z", text="Split Z-Axis (Height)")
        if props.chunk_split_z:
            box_chunk.prop(props, "chunk_cell_size_z", text="Z Cell Size (m)")

        box_hlod = layout.box()
        box_hlod.label(text="Hierarchical LOD (HLOD)", icon="STICKY_UVS_DISABLE")
        box_hlod.prop(props, "enable_hlod", text="Enable HLOD Merging")
        if props.enable_hlod:
            box_hlod.prop(props, "hlod_start_tier", text="Merge From Tier")

        col_chunk = layout.column(align=True)
        col_chunk.scale_y = 1.3
        col_chunk.operator(
            "lod_tool.spatial_chunk_and_generate", text="Partition & Generate Chunked LODs", icon="MOD_BUILD"
        )


# Strict Parent-First Topological Registration Order
PANEL_CLASSES = (
    OMNIMESH_PT_import,
    OMNIMESH_PT_fix_lod0,
    OMNIMESH_PT_lods,
    OMNIMESH_PT_inspection_sub,
    OMNIMESH_PT_optimization_sub,
    OMNIMESH_PT_chunking_sub,
    OMNIMESH_PT_export,
    OMNIMESH_PT_batch_sub,
)


def register_panel() -> None:
    if not bpy:
        return
    for cls in PANEL_CLASSES:
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:
            logger.debug("Safe unregister skipped %s: %s", getattr(cls, "__name__", "cls"), exc)
        bpy.utils.register_class(cls)


def unregister_panel() -> None:
    if not bpy:
        return
    for cls in reversed(PANEL_CLASSES):
        bpy.utils.unregister_class(cls)
