"""
OmniMesh Popover Panels for Blender 4.2+ and 5.2 LTS.
Declares secondary configuration popovers invoked via gear icons (`layout.popover`).

Design Invariants:
- Omit `bl_category` to prevent ghost tabs in the N-Panel.
- Omit `bl_parent_id` to prevent accordion collision.
- Declare `bl_ui_units_x = 16` to prevent label/slider truncation in popups.
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
except (ImportError, ValueError):
    from core.pbr_presets import (
        DEFAULT_PRESET_ID,
        PBRExportPresetManager,
        PBRImportPresetManager,
    )


# =========================================================================
# =========================================================================
# 2. MODIFY POPOVERS: SANITIZE & MATERIALS
# =========================================================================


class OMNIMESH_PT_popover_sanitize(Panel):
    """Popover for mesh sanitization, transform normalization, and geometry repair settings."""

    bl_idname = "OMNIMESH_PT_popover_sanitize"
    bl_label = "Sanitization Settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 16

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        # 1. Transform & Modifiers
        layout.label(text="Transform & Modifiers", icon="OBJECT_ORIGIN")
        layout.prop(props, "cleanup_auto_apply_transforms", text="Auto-Apply Transforms")
        layout.prop(props, "cleanup_apply_modifiers", text="Bake / Apply Modifiers")
        row_t = layout.row(align=True)
        row_t.operator("lod_tool.apply_transforms", text="Apply Transforms", icon="CHECKMARK")
        row_t.operator("lod_tool.apply_all_modifiers", text="Apply Modifiers", icon="MODIFIER")

        layout.separator()

        # 2. Topology Repair Options
        layout.label(text="Topology Repair Options", icon="PREFERENCES")
        layout.prop(props, "cleanup_enable_split_non_manifold", text="Repair Non-Manifold & Bowties")
        layout.prop(props, "cleanup_normal_policy", text="Normals")

        row_w = layout.row(align=True)
        row_w.prop(props, "cleanup_enable_weld", text="Merge Close")
        if props.cleanup_enable_weld:
            row_w.prop(props, "cleanup_weld_distance", text="Dist")

        row_h = layout.row(align=True)
        row_h.prop(props, "cleanup_enable_fill_holes", text="Fill Holes")
        if props.cleanup_enable_fill_holes:
            row_h.prop(props, "cleanup_hole_max_edges", text="Max Edges")

        layout.prop(props, "cleanup_enable_triangulate_ngons", text="Triangulate N-Gons")


class OMNIMESH_PT_popover_materials(Panel):
    """Popover for material cleanup, AST-hash deduplication, and micro-material consolidation."""

    bl_idname = "OMNIMESH_PT_popover_materials"
    bl_label = "Material Cleanup Settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 16

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        layout.label(text="Safe Operations (Default ON)", icon="CHECKMARK")
        layout.prop(props, "mat_cleanup_purge_unused_slots", text="Purge Unused Slots")
        layout.prop(props, "mat_cleanup_deduplicate_slots", text="Deduplicate Repeated Slots")
        layout.prop(props, "mat_cleanup_merge_duplicate_datablocks", text="Merge Duplicate Materials (AST Hash)")
        layout.prop(props, "mat_cleanup_remove_orphan_nodes", text="Remove Dead Shader Nodes")

        layout.separator()
        layout.label(text="Critical Operations (Opt-In)", icon="ERROR")
        layout.prop(props, "mat_cleanup_enable_micro_consolidation", text="Consolidate Micro-Materials")
        if props.mat_cleanup_enable_micro_consolidation:
            layout.prop(props, "mat_cleanup_micro_area_pct", text="Threshold %")
        layout.prop(props, "mat_cleanup_repair_missing_textures", text="Repair Missing Textures")
        layout.prop(props, "mat_cleanup_purge_orphans_blendfile", text="Purge Orphan Materials from .blend")


class OMNIMESH_PT_popover_collision(Panel):
    """Popover for convex collision hull generation and physics decomposition settings."""

    bl_idname = "OMNIMESH_PT_popover_collision"
    bl_label = "Collision Hull Settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 16

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        layout.label(text="Physics Decomposition", icon="MOD_PHYSICS")
        layout.prop(props, "collision_decomposition_mode", text="Mode")

        if props.collision_decomposition_mode in {"PER_OBJECT", "CONSOLIDATED"}:
            layout.prop(props, "collision_hull_count", text="Hull Count")
            layout.prop(props, "collision_concavity_threshold", text="Concavity (m)")

        layout.separator()
        layout.label(text="Engine Constraints", icon="PREFERENCES")
        layout.prop(props, "collision_max_verts_per_hull", text="Max Verts / Hull")


# =========================================================================
# 3. LODs POPOVERS: CONFIGURE & GENERATION
# =========================================================================


class OMNIMESH_PT_popover_configure(Panel):
    """Popover for LOD auto-configuration and target engine rules."""

    bl_idname = "OMNIMESH_PT_popover_configure"
    bl_label = "LOD Tier Configuration"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 16

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        layout.label(text="Target Engine & Asset Role", icon="SCENE_DATA")
        layout.prop(props, "target_engine", text="Engine")
        layout.prop(props, "asset_category", text="Role")
        layout.prop(props, "export_base_name", text="Asset Name")

        layout.separator()
        layout.label(text="Quality & Screen Tolerances", icon="RESTRICT_VIEW_OFF")
        layout.prop(props, "tau_sse", slider=True, text="Visual Stability (SSE)")
        layout.prop(props, "cull_screen_size_pct", slider=True, text="Cull Screen Size (%)")
        if props.target_engine != "MSFS_2024":
            layout.prop(props, "num_lods", text="LOD Tier Count")


class OMNIMESH_PT_popover_generate(Panel):
    """Popover for advanced LOD generation heuristics (Rigging, Draw-Calls, Chunking)."""

    bl_idname = "OMNIMESH_PT_popover_generate"
    bl_label = "Generation & Optimization Settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 16

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        layout.label(text="Hierarchy & Draw-Calls", icon="OUTLINER_OB_GROUP_INSTANCE")
        layout.prop(props, "hierarchy_mode", text="Mode")
        if props.hierarchy_mode == "MERGE_AT_TIER":
            layout.prop(props, "merge_start_tier", text="Merge From Tier")
        layout.prop(props, "preserve_slot_indexing", text="Preserve Slot Indexing")

        layout.separator()
        layout.label(text="Rigging & Deform Kinematics", icon="ARMATURE_DATA")
        layout.prop(props, "max_bone_influences", text="Max Bone Influences")
        layout.prop(props, "enable_bone_pruning", text="Leaf Bone Pruning")
        layout.prop(props, "purge_shape_keys", text="Purge Distant Shape Keys")


class OMNIMESH_PT_popover_lod_preset(Panel):
    """Popover for configuring the active LOD preset, quality curve, and generation heuristics."""

    bl_idname = "OMNIMESH_PT_popover_lod_preset"
    bl_label = "LOD Profile Settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 22

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        try:
            from core.lod_presets import DEFAULT_LOD_PRESET_ID, LODPresetManager
        except (ImportError, ValueError):
            from ..core.lod_presets import DEFAULT_LOD_PRESET_ID, LODPresetManager

        preset_id = getattr(props, "lod_preset", "") or DEFAULT_LOD_PRESET_ID
        preset = LODPresetManager.get_preset(preset_id)

        # 1. Header & Quality Curve
        layout.label(text=preset.get("name", preset_id), icon="PRESET")
        desc = preset.get("description", "")
        if desc:
            layout.label(text=desc)

        layout.prop(props, "tau_sse", slider=True, text="Visual Stability (τ)")

        layout.separator()

        # 2. Preset Tiers (Compact Overview)
        row_hdr = layout.row(align=True)
        row_hdr.label(text="Preset Tiers & Budgets", icon="MESH_DATA")

        row = layout.row()
        active_count = len(props.lod_preset_active_tiers)
        list_rows = max(3, min(active_count, 5))
        row.template_list(
            "OMNIMESH_UL_preset_tiers",
            "",
            props,
            "lod_preset_active_tiers",
            props,
            "lod_preset_active_tier_index",
            rows=list_rows,
            maxrows=5,
        )
        col_btn = row.column(align=True)
        col_btn.operator("lod_tool.add_preset_tier", icon="ADD", text="")
        sub_rem = col_btn.column(align=True)
        sub_rem.enabled = len(props.lod_preset_active_tiers) > 1
        sub_rem.operator("lod_tool.remove_preset_tier", icon="REMOVE", text="")

        # Cull Screen Size threshold immediately beneath the tiers
        row_cull = layout.row(align=True)
        row_cull.prop(props, "cull_screen_size_pct", slider=True, text="Cull at Screen Size")

        layout.separator()

        # 3. Hierarchy & Draw-Calls
        box_hier = layout.box()
        box_hier.use_property_split = True
        box_hier.use_property_decorate = False
        box_hier.prop(props, "consolidate_hierarchy", text="Consolidate Hierarchy")

        # 4. Occlusion & Slender Culling
        box_cull = layout.box()
        box_cull.use_property_split = True
        box_cull.use_property_decorate = False
        box_cull.label(text="Occlusion & Slender Culling", icon="HIDE_OFF")
        box_cull.prop(props, "enable_occlusion_culling", text="Interior Culling")
        if props.enable_occlusion_culling:
            box_cull.prop(props, "occlusion_lod_start", text="Start Tier")
            box_cull.prop(props, "occlusion_ray_density", text="Ray Samples")
            box_cull.prop(props, "occlusion_evaluate_alpha", text="Eval Alpha")
        box_cull.prop(props, "enable_slender_culling", text="Slender Culling")

        # 5. Spatial Chunking & HLOD
        box_chunk = layout.box()
        box_chunk.use_property_split = True
        box_chunk.use_property_decorate = False
        box_chunk.label(text="Spatial Chunking & HLOD", icon="MESH_GRID")
        box_chunk.prop(props, "enable_spatial_chunking", text="Enable Chunking")
        if props.enable_spatial_chunking:
            box_chunk.prop(props, "chunk_partitioning_mode", text="Partitioning")
            if props.chunk_partitioning_mode == "ADAPTIVE_CLUSTERING":
                box_chunk.prop(props, "adaptive_cluster_target_polys", text="Max Polys/Cluster")
            box_chunk.prop(props, "chunk_cell_size", text="Cell Size (m)")
            box_chunk.prop(props, "chunk_split_z", text="Split Vertical Z")
            if props.chunk_split_z:
                box_chunk.prop(props, "chunk_cell_size_z", text="Z Cell Size (m)")
            box_chunk.prop(props, "enable_hlod", text="Enable HLOD")
            if props.enable_hlod:
                box_chunk.prop(props, "hlod_start_tier", text="HLOD Start Tier")

        # 6. Billboard Impostor
        box_imp = layout.box()
        box_imp.use_property_split = True
        box_imp.use_property_decorate = False
        box_imp.label(text="Billboard Impostor", icon="IMAGE_PLANE")
        box_imp.prop(props, "enable_impostor_lod", text="Enable Impostor")
        if props.enable_impostor_lod:
            box_imp.prop(props, "impostor_mode", text="Mode")
            box_imp.prop(props, "auto_impostor_resolution", text="Auto Resolution")
            if not getattr(props, "auto_impostor_resolution", True):
                box_imp.prop(props, "impostor_resolution", text="Resolution")
            else:
                # Informational label of calculated resolution
                s_pct = props.lods[-1].screen_size_pct if len(props.lods) > 0 else 5.0
                target_px = max(256, min(4096, int(2048 * (s_pct / 10.0))))
                calc_res = 1 << (target_px - 1).bit_length()
                calc_res = max(256, min(4096, calc_res))
                row_calc = box_imp.row()
                row_calc.label(text=f"Calculated: {calc_res}×{calc_res}", icon="INFO")

        layout.separator()
        row_act = layout.row(align=True)
        row_act.operator("lod_tool.analyze_and_configure", text="Reset to Factory", icon="LOOP_BACK")
        if LODPresetManager.is_user_preset(preset_id):
            row_act.operator("lod_tool.delete_lod_preset", text="Delete Preset", icon="TRASH")


class OMNIMESH_PT_popover_impostor(Panel):
    """Dedicated Quick Configuration Popover for Billboard Impostors."""

    bl_label = "Billboard Impostor Settings"
    bl_idname = "OMNIMESH_PT_popover_impostor"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 18

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        layout.label(text="Billboard Impostor Settings", icon="IMAGE_PLANE")
        box = layout.box()
        box.use_property_split = True
        box.use_property_decorate = False
        box.prop(props, "impostor_mode", text="Mode")
        box.prop(props, "impostor_resolution", text="Resolution")
        box.prop(props, "impostor_replace_last_lod", text="Final LOD Tier")

        layout.separator()
        row_act = layout.row(align=True)
        row_act.scale_y = 1.25
        row_act.operator("lod_tool.generate_impostor", text="Generate", icon="IMAGE_PLANE")
        row_act.operator("lod_tool.remove_impostor", text="Remove", icon="X")


# =========================================================================
# 4. EXPORT POPOVERS: PACKAGE & BRIDGE
# =========================================================================


class OMNIMESH_PT_popover_export(Panel):
    """Popover for single asset export packaging, texture packing, and animation baking."""

    bl_idname = "OMNIMESH_PT_popover_export"
    bl_label = "Package Export Settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 16

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        layout.label(text="PBR Texture Export & Packing", icon="NODE_MATERIAL")
        layout.prop(props, "export_packed_textures", text="Pack PBR Textures")
        if props.export_packed_textures:
            box = layout.box()
            box.prop(props, "pbr_export_preset", text="Preset")
            box.prop(props, "pbr_export_texture_strategy", text="Strategy")
            box.prop(props, "texture_max_resolution", text="Resolution")
            box.prop(props, "pbr_export_bit_depth", text="Bit Depth")
            box.prop(props, "pbr_export_naming_pattern", text="Naming")
            box.operator("lod_tool.pack_pbr_textures", text="Pack Textures Now", icon="IMAGE_DATA")

        layout.separator()
        layout.label(text="Rig Animations", icon="ACTION")
        layout.prop(props, "bake_animations", text="Bake Skeletal Animations")


class OMNIMESH_PT_popover_import_preset(Panel):
    """Popover for configuring the selected import preset and editing texture map rules."""

    bl_idname = "OMNIMESH_PT_popover_import_preset"
    bl_label = "Import Preset Settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 22

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        preset_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID
        preset = PBRImportPresetManager.get_preset(preset_id)

        # Hydrate maps if collection is empty or if active preset has changed
        cached_pid = getattr(props, "pbr_active_maps_preset_id", "")
        if len(props.pbr_active_maps) == 0 or cached_pid != preset_id:
            try:
                from .properties import sync_maps_from_preset
            except (ImportError, ValueError):
                try:
                    from ui.properties import sync_maps_from_preset
                except (ImportError, ValueError):
                    sync_maps_from_preset = None
            if sync_maps_from_preset:
                sync_maps_from_preset(props, preset)

        layout.label(text=preset.get("name", preset_id), icon="PRESET")
        desc = preset.get("description", "")
        if desc:
            layout.label(text=desc)

        layout.separator()
        layout.label(text="Texture Path & Routing", icon="IMAGE_DATA")
        layout.prop(props, "pbr_import_path_mode", text="Path Mode")
        layout.prop(props, "pbr_import_ao_mode", text="AO Routing")
        layout.prop(props, "pbr_import_preserve_existing", text="Preserve Other Nodes")

        layout.separator()
        layout.label(text="Texture Map Rules", icon="NODE_MATERIAL")

        row = layout.row()
        active_count = len(props.pbr_active_maps)
        list_rows = max(4, min(active_count, 7))
        row.template_list(
            "OMNIMESH_UL_preset_maps",
            "",
            props,
            "pbr_active_maps",
            props,
            "pbr_active_map_index",
            rows=list_rows,
            maxrows=8,
        )
        col_btn = row.column(align=True)
        col_btn.operator("lod_tool.add_preset_map", icon="ADD", text="")
        sub_rem = col_btn.column(align=True)
        sub_rem.enabled = len(props.pbr_active_maps) > 1
        sub_rem.operator("lod_tool.delete_preset_map", icon="REMOVE", text="")

        maps = props.pbr_active_maps
        idx = props.pbr_active_map_index
        if 0 <= idx < len(maps):
            active_map = maps[idx]
            box_detail = layout.box()
            col = box_detail.column(align=True)
            col.prop(active_map, "name", text="Name")
            col.prop(active_map, "suffixes_str", text="Suffixes")

            row_cs = col.row(align=True)
            row_cs.prop(active_map, "color_space", text="Color Space")
            row_cs.prop(active_map, "priority", text="Priority")

            col.prop(active_map, "is_normal_map", text="Is Normal Map")
            if active_map.is_normal_map:
                col.prop(active_map, "normal_format", text="Normal Format")

            col.separator()
            col.prop(active_map, "is_packed", text="Packed (R/G/B/A)")

            if not active_map.is_packed:
                col.prop(active_map, "target_rgb", text="Target Socket")
                row_a = col.row(align=True)
                row_a.prop(active_map, "target_a", text="Alpha Socket")
                row_a.prop(active_map, "invert_a", text="Invert")
            else:
                for ch in ("r", "g", "b", "a"):
                    row_ch = col.row(align=True)
                    row_ch.prop(active_map, f"target_{ch}", text=f"{ch.upper()} Socket")
                    row_ch.prop(active_map, f"invert_{ch}", text="Invert")


class OMNIMESH_PT_popover_export_preset(Panel):
    """Popover for configuring the selected export preset (Strategy, Bit Depth, Naming, Maps)."""

    bl_idname = "OMNIMESH_PT_popover_export_preset"
    bl_label = "Export Profile Settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 22

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        preset_id = getattr(props, "pbr_export_preset", "") or DEFAULT_PRESET_ID
        preset = PBRExportPresetManager.get_preset(preset_id)

        # Hydrate maps if collection is empty or if active preset has changed
        cached_pid = getattr(props, "pbr_export_active_maps_preset_id", "")
        if len(props.pbr_export_active_maps) == 0 or cached_pid != preset_id:
            try:
                from .properties import sync_export_maps_from_preset
            except (ImportError, ValueError):
                try:
                    from ui.properties import sync_export_maps_from_preset
                except (ImportError, ValueError):
                    sync_export_maps_from_preset = None
            if sync_export_maps_from_preset:
                sync_export_maps_from_preset(props, preset)

        layout.label(text=preset.get("name", preset_id), icon="PRESET")
        desc = preset.get("description", "")
        if desc:
            layout.label(text=desc)

        layout.separator()
        layout.label(text="Preset Configuration", icon="SETTINGS")
        layout.prop(props, "pbr_export_texture_strategy", text="Strategy")
        if props.pbr_export_texture_strategy in {"SMART_AUTO", "BAKE"}:
            layout.prop(props, "texture_max_resolution", text="Bake Resolution")
        layout.prop(props, "pbr_export_bit_depth", text="Bit Depth")
        layout.prop(props, "pbr_export_naming_pattern", text="Naming Pattern")

        layout.separator()
        layout.label(text="Package Pipeline Toggles", icon="PACKAGE")
        layout.prop(props, "export_packed_textures", text="Pack PBR Textures on Export")
        layout.prop(props, "bake_animations", text="Bake Skeletal Animations")
        layout.prop(props, "engine_project_path", text="Engine Project Path (Bridge)")

        layout.separator()
        layout.label(text="Export Maps & Channel Routing", icon="NODE_MATERIAL")

        row = layout.row()
        row.template_list(
            "OMNIMESH_UL_export_preset_maps",
            "",
            props,
            "pbr_export_active_maps",
            props,
            "pbr_export_active_map_index",
            rows=min(max(len(props.pbr_export_active_maps), 2), 5),
        )
        col_btn = row.column(align=True)
        col_btn.operator("lod_tool.add_export_preset_map", icon="ADD", text="")
        col_btn.operator("lod_tool.delete_export_preset_map", icon="REMOVE", text="")

        # Detail box for selected map
        idx = props.pbr_export_active_map_index
        if 0 <= idx < len(props.pbr_export_active_maps):
            active_map = props.pbr_export_active_maps[idx]
            box = layout.box()
            box.use_property_split = True
            box.use_property_decorate = False

            row_top = box.row(align=True)
            row_top.prop(active_map, "name", text="Map Name")
            row_top.prop(active_map, "export", text="Export")

            box.prop(active_map, "export_suffix", text="Suffix")
            box.prop(active_map, "color_space", text="Color Space")

            row_norm = box.row()
            row_norm.prop(active_map, "is_normal_map", text="Normal Map")
            if active_map.is_normal_map:
                row_norm.prop(active_map, "normal_format", text="")

            box.prop(active_map, "is_packed", text="Channel Packed")

            col = box.column(align=True)
            if not active_map.is_packed:
                col.prop(active_map, "target_rgb", text="RGB Socket")
                row_a = col.row(align=True)
                row_a.prop(active_map, "target_a", text="Alpha Socket")
                row_a.prop(active_map, "invert_a", text="Invert")
            else:
                for ch in ("r", "g", "b", "a"):
                    row_ch = col.row(align=True)
                    row_ch.prop(active_map, f"target_{ch}", text=f"{ch.upper()} Socket")
                    row_ch.prop(active_map, f"invert_{ch}", text="Invert")


class OMNIMESH_PT_popover_engine_import_preset(Panel):
    """Popover for configuring engine project package import options (toggles, model target, optimization)."""

    bl_idname = "OMNIMESH_PT_popover_engine_import_preset"
    bl_label = "Engine Import Settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 20

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        try:
            from ..core.engine_import_presets import (
                DEFAULT_ENGINE_IMPORT_PRESET_ID,
                EngineImportPresetManager,
            )
        except (ImportError, ValueError):
            from core.engine_import_presets import (
                DEFAULT_ENGINE_IMPORT_PRESET_ID,
                EngineImportPresetManager,
            )

        preset_id = getattr(props, "engine_import_preset", "") or DEFAULT_ENGINE_IMPORT_PRESET_ID
        preset = EngineImportPresetManager.get_preset(preset_id)

        layout.label(text=preset.get("name", preset_id), icon="PACKAGE")
        desc = preset.get("description", "")
        if desc:
            layout.label(text=desc)

        layout.separator()
        layout.label(text="Package Components to Ingest", icon="CHECKBOX_HLT")
        box_comp = layout.box()
        box_comp.prop(props, "engine_import_geometry", text="Geometry & Multi-LODs")
        box_comp.prop(props, "engine_import_spatial", text="Spatial Markers (Datum, CG, Wheels)")
        box_comp.prop(props, "engine_import_lights", text="Aviation Lights (Nav, Strobe, Landing)")
        box_comp.prop(props, "engine_import_cameras", text="Cameras (Pilot, Cockpit, External)")

        layout.separator()
        layout.label(text="Model Target Selection", icon="OUTLINER_OB_MESH")
        layout.prop(props, "engine_import_model_target", text="Target")

        layout.separator()
        layout.label(text="Pipeline Optimizations", icon="MODIFIER")
        box_opt = layout.box()
        box_opt.prop(props, "engine_import_use_lod0_suffix", text="Use '_LOD0' Suffix")
        box_opt.prop(props, "engine_import_auto_assign_screen_pct", text="Auto-Assign minSize to Screen %")
        box_opt.prop(props, "engine_import_deduplicate_materials", text="Deduplicate Re-imported Materials")
        box_opt.prop(props, "engine_import_reuse_master_rig", text="Reuse Master Armature Rig")


POPOVER_CLASSES = (
    OMNIMESH_PT_popover_engine_import_preset,
    OMNIMESH_PT_popover_import_preset,
    OMNIMESH_PT_popover_sanitize,
    OMNIMESH_PT_popover_materials,
    OMNIMESH_PT_popover_collision,
    OMNIMESH_PT_popover_configure,
    OMNIMESH_PT_popover_generate,
    OMNIMESH_PT_popover_lod_preset,
    OMNIMESH_PT_popover_impostor,
    OMNIMESH_PT_popover_export,
    OMNIMESH_PT_popover_export_preset,
)
