"""
Modular N-Panel User Interface Hierarchy for OmniMesh in Blender 4.2+ and 5.2 LTS.
Structured into clean, workflow-oriented collapsible subpanels with responsive layouts.
Supports Per-Object property persistence, Sub-LOD derivative inspection, multi-selection batch sync,
and distinct safe vs critical mesh & material cleanup controls.
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
    from .operators import get_associated_armature, get_selected_mesh_objects, resolve_lod_context
except (ImportError, ValueError):
    from ui.operators import get_associated_armature, get_selected_mesh_objects, resolve_lod_context


class LOD_PT_main_panel(Panel):
    """OmniMesh Root Panel: Target Engine & Asset Setup."""

    bl_label = "OmniMesh"
    bl_idname = "LOD_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OmniMesh"

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        scene_props, obj_props, master_obj, is_derivative = resolve_lod_context(context)
        props = obj_props or scene_props

        # Sub-LOD Derivative Inspection Mode Banner
        if is_derivative and master_obj:
            box_der = layout.box()
            box_der.alert = True
            box_der.label(text=f"Inspection: Generated Sub-LOD of '{master_obj.name}'", icon="INFO")
            box_der.operator(
                "lod_tool.select_master_asset",
                text=f"Select Master Asset ({master_obj.name})",
                icon="OBJECT_DATA",
            )

        # Multi-Selection Sync CTA
        selected_meshes = get_selected_mesh_objects(context)
        if len(selected_meshes) > 1:
            box_sync = layout.box()
            row_sync = box_sync.row(align=True)
            row_sync.operator(
                "lod_tool.sync_selection_settings",
                text=f"Copy Settings to {len(selected_meshes) - 1} Selected",
                icon="DUPLICATE",
            )

        # 1. Project & Target Engine Setup Card (Scene-Level)
        box = layout.box()
        box.label(text="1. Target Engine & Preset", icon="SCENE_DATA")
        box.prop(scene_props, "target_engine", text="")
        box.prop(props, "asset_category", text="")
        box.prop(props, "export_base_name", text="Asset Name")

        # 2. Quality & Screen-Space Error Card (Object-Level)
        box_q = layout.box()
        box_q.label(text="Quality & Tolerance", icon="RESTRICT_VIEW_OFF")
        box_q.prop(props, "progression_mode", text="Curve")
        box_q.prop(props, "lod_count", text="LOD Count")

        # Step 1 Primary CTA
        col_cta = layout.column(align=True)
        col_cta.scale_y = 1.3
        col_cta.operator("lod_tool.analyze_and_configure", text="1. Auto-Configure Tiers", icon="VIEWZOOM")


class LOD_PT_tiers_panel(Panel):
    """Subpanel 1: Configured LOD Tiers, Generation Action Card & Isolation Grid."""

    bl_label = "2. LOD Tiers & Geometry"
    bl_idname = "LOD_PT_tiers_panel"
    bl_parent_id = "LOD_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_order = 0

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        _, obj_props, _, _ = resolve_lod_context(context)
        props = obj_props or context.scene.lod_tool

        if not props.lods:
            box = layout.box()
            box.label(text="No tiers configured.", icon="INFO")
            box.label(text="Click '1. Auto-Configure Tiers' above.")
            return

        # UIList Table
        box = layout.box()
        box.template_list("LOD_UL_tier_list", "", props, "lods", props, "active_lod_index", rows=len(props.lods))

        # Selected Tier Inspection Detail
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

        # Post-Generation Summary Metrics Banner
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


class LOD_PT_inspection_panel(Panel):
    """Subpanel 2: Viewport Inspection, Real-Time LOD Simulator & A/B Split Preview."""

    bl_label = "3. Viewport Inspection & Simulator"
    bl_idname = "LOD_PT_inspection_panel"
    bl_parent_id = "LOD_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 1

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        # Real-Time Distance Simulator Loop
        box_sim = layout.box()
        box_sim.label(text="Live Distance Simulator", icon="CAMERA_DATA")
        row_sim = box_sim.row(align=True)
        row_sim.scale_y = 1.25
        if props.is_simulator_active:
            row_sim.operator("lod_tool.toggle_simulator", text="Stop Live Simulator", icon="CANCEL")
        else:
            row_sim.operator("lod_tool.toggle_simulator", text="Start Live Simulator", icon="PLAY")

        if props.is_simulator_active:
            box_sim.prop(props, "simulator_camera_mode", text="Camera")
            box_sim.prop(props, "virtual_distance_override", slider=True, text="Virtual Slider (m)")

        # Visual A/B Split-Screen Viewport Preview
        box_split = layout.box()
        box_split.label(text="A/B Split-Screen Comparison", icon="SPLITVIEW")
        row_split = box_split.row(align=True)
        row_split.scale_y = 1.2
        if props.is_split_active:
            row_split.operator("lod_tool.toggle_split_preview", text="Exit Split Preview", icon="CANCEL")
            box_split.prop(props, "split_ratio", slider=True, text="Divider Position")
        else:
            row_split.operator("lod_tool.toggle_split_preview", text="Start Split Preview", icon="VIEW_CAMERA")
        box_split.prop(props, "split_compare_tier", text="Compare Tier")

        # Viewport HUD Toggle
        box_hud = layout.box()
        box_hud.prop(props, "show_viewport_hud", text="Show Viewport HUD Overlay", icon="WINDOW")


class LOD_PT_optimization_panel(Panel):
    """Subpanel 3: Topology Cleanup, Material Cleanup, Collision Hulls, Impostors, Occlusion, Rigging & PBR Textures."""

    bl_label = "4. Advanced Optimization"
    bl_idname = "LOD_PT_optimization_panel"
    bl_parent_id = "LOD_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 2

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        scene_props, obj_props, _, _ = resolve_lod_context(context)
        props = obj_props or scene_props
        mesh_objs = get_selected_mesh_objects(context)
        armature_obj = get_associated_armature(mesh_objs)

        # 1. Mesh Topology Cleanup & Repair Suite
        box_cl = layout.box()
        box_cl.label(text="Mesh Topology Cleanup & Repair", icon="BRUSH_DATA")
        row_cl = box_cl.row(align=True)
        row_cl.scale_y = 1.25
        row_cl.operator("lod_tool.clean_and_repair_mesh", text="Clean & Repair Meshes", icon="AUTO")

        if props.last_cleanup_summary:
            box_cl.label(text=props.last_cleanup_summary, icon="CHECKMARK")

        box_cl.prop(props, "auto_sanitize_before_lod", text="Auto-Hygiene Before LOD")

        # Mesh Critical & Opt-in Toggles Sub-Box
        box_opt = box_cl.box()
        box_opt.label(text="Critical & Opt-In Settings", icon="PREFERENCES")
        box_opt.prop(props, "cleanup_enable_split_non_manifold")
        box_opt.prop(props, "cleanup_normal_policy", text="Normals")

        row_w = box_opt.row(align=True)
        row_w.prop(props, "cleanup_enable_weld", text="Merge Close")
        if props.cleanup_enable_weld:
            row_w.prop(props, "cleanup_weld_distance", text="Dist")

        row_h = box_opt.row(align=True)
        row_h.prop(props, "cleanup_enable_fill_holes", text="Fill Holes")
        if props.cleanup_enable_fill_holes:
            row_h.prop(props, "cleanup_hole_max_edges", text="Max Edges")

        row_i = box_opt.row(align=True)
        row_i.prop(props, "cleanup_enable_cull_micro_islands", text="Cull Islands")
        if props.cleanup_enable_cull_micro_islands:
            row_i.prop(props, "cleanup_island_size_threshold", text="Size")

        # 2. Material Cleanup & Slot Consolidation Suite
        box_mat = layout.box()
        box_mat.label(text="Material Cleanup & Consolidation", icon="MATERIAL")
        row_mat = box_mat.row(align=True)
        row_mat.scale_y = 1.25
        row_mat.operator("lod_tool.clean_and_repair_materials", text="Clean Materials", icon="MATERIAL_DATA")

        if props.last_material_cleanup_summary:
            box_mat.label(text=props.last_material_cleanup_summary, icon="CHECKMARK")

        # Safe Material Toggles
        box_mat_safe = box_mat.box()
        box_mat_safe.label(text="Safe Operations (Default ON)", icon="CHECKMARK")
        box_mat_safe.prop(props, "mat_cleanup_purge_unused_slots")
        box_mat_safe.prop(props, "mat_cleanup_deduplicate_slots")
        box_mat_safe.prop(props, "mat_cleanup_merge_duplicate_datablocks")
        box_mat_safe.prop(props, "mat_cleanup_remove_orphan_nodes")

        # Critical / Opt-In Material Toggles
        box_mat_crit = box_mat.box()
        box_mat_crit.label(text="Critical Operations (Opt-In)", icon="ERROR")
        box_mat_crit.prop(props, "mat_cleanup_enable_micro_consolidation")
        if props.mat_cleanup_enable_micro_consolidation:
            box_mat_crit.prop(props, "mat_cleanup_micro_area_pct", text="Threshold %")
        box_mat_crit.prop(props, "mat_cleanup_repair_missing_textures")
        box_mat_crit.prop(props, "mat_cleanup_purge_orphans_blendfile")

        # 3. Multi-Convex Collision Hulls (Physics)
        box_col = layout.box()
        box_col.label(text="Convex Collision Hulls (Physics)", icon="PHYSICS")
        box_col.prop(props, "collision_decomposition_mode", text="")
        box_col.prop(props, "collision_hull_count")
        box_col.prop(props, "collision_max_verts_per_hull")
        box_col.prop(props, "collision_concavity_threshold")

        row_c = box_col.row(align=True)
        row_c.scale_y = 1.2
        row_c.operator("lod_tool.generate_collision_hulls", text="Generate Colliders", icon="MESH_ICOSPHERE")
        row_c.operator("lod_tool.remove_collision_hulls", text="", icon="TRASH")

        if props.last_generated_collider_count > 0:
            box_col.label(
                text=f"✔ Active: {props.last_generated_collider_count} Convex Hulls (Wire)",
                icon="CHECKMARK",
            )

        # 4. Billboard & Octahedral Impostor Generator
        box_imp = layout.box()
        box_imp.label(text="Billboard & Octahedral Impostor", icon="OUTLINER_OB_LIGHTPROBE")
        box_imp.prop(props, "impostor_mode", text="")
        box_imp.prop(props, "impostor_resolution")
        box_imp.prop(props, "impostor_replace_last_lod")

        row_imp = box_imp.row(align=True)
        row_imp.scale_y = 1.2
        row_imp.operator("lod_tool.generate_impostor", text="Generate Impostor", icon="MESH_PLANE")
        row_imp.operator("lod_tool.remove_impostor", text="", icon="TRASH")

        if props.last_impostor_status:
            box_imp.label(text=props.last_impostor_status, icon="CHECKMARK")

        # 5. Interior & Occlusion Geometry Culling
        box_occ = layout.box()
        box_occ.label(text="Interior & Occlusion Culling", icon="MOD_MASK")
        box_occ.prop(props, "enable_occlusion_culling")
        if props.enable_occlusion_culling:
            box_occ.prop(props, "occlusion_lod_start")
            box_occ.prop(props, "occlusion_ray_density")
            box_occ.prop(props, "occlusion_evaluate_alpha")
            if props.last_culled_faces_count > 0:
                box_occ.label(
                    text=f"Culled {props.last_culled_faces_count:,} interior faces ({props.last_culled_islands_count} islands)",
                    icon="CHECKMARK",
                )

        # 6. Hierarchy & Draw-Call Optimization
        box_h = layout.box()
        box_h.label(text="Draw-Call Merging", icon="OUTLINER_OB_GROUP_INSTANCE")
        box_h.prop(props, "hierarchy_mode", text="")
        if props.hierarchy_mode == "MERGE_DISTANT":
            box_h.prop(props, "merge_lod_start")

        # 7. Rigging & Skeletal Kinematics
        box_r = layout.box()
        box_r.label(text="Rigging & Skeletal Kinematics", icon="ARMATURE_DATA")
        has_skinning = bool(armature_obj or any(len(obj.vertex_groups) > 0 for obj in mesh_objs))
        if not has_skinning:
            box_r.label(text="No Armature or Deform Groups Detected", icon="INFO")
        col_rig = box_r.column()
        col_rig.active = has_skinning
        col_rig.prop(props, "max_bone_influences")
        col_rig.prop(props, "enable_leaf_bone_pruning")
        col_rig.prop(props, "purge_distant_shape_keys")

        # 8. PBR Texture Channel Packing & Animation
        box_tex = layout.box()
        box_tex.label(text="PBR Textures & Rig Animations", icon="NODE_MATERIAL")
        box_tex.prop(props, "export_packed_textures")
        if props.export_packed_textures:
            box_tex.prop(props, "texture_max_resolution")
            box_tex.operator("lod_tool.pack_pbr_textures", icon="IMAGE_DATA")
        box_tex.prop(props, "bake_animations")
        if props.bake_animations:
            box_tex.operator("lod_tool.bake_rig_animation", icon="ACTION")


class LOD_PT_export_bridge_panel(Panel):
    """Subpanel 4: Multi-Engine Package Export & Live Engine Bridge."""

    bl_label = "5. Export & Live Engine Bridge"
    bl_idname = "LOD_PT_export_bridge_panel"
    bl_parent_id = "LOD_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_options = {"DEFAULT_CLOSED"}
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
        col_exp.scale_y = 1.2
        col_exp.operator("lod_tool.export_engine_package", text="Export Engine Package", icon="PACKAGE")

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


class LOD_PT_batch_panel(Panel):
    """Subpanel 5: Batch Asset Library Ingestion."""

    bl_label = "6. Batch Library Ingestion"
    bl_idname = "LOD_PT_batch_panel"
    bl_parent_id = "LOD_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 4

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
    LOD_PT_main_panel,
    LOD_PT_tiers_panel,
    LOD_PT_inspection_panel,
    LOD_PT_optimization_panel,
    LOD_PT_export_bridge_panel,
    LOD_PT_batch_panel,
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
