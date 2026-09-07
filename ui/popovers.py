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
# 1. IMPORT POPOVER
# =========================================================================


class OMNIMESH_PT_popover_import(Panel):
    """Popover for PBR texture import settings."""

    bl_idname = "OMNIMESH_PT_popover_import"
    bl_label = "PBR Import Settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 16

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        layout.label(text="Texture Routing & Protection", icon="IMAGE_DATA")
        layout.prop(props, "pbr_import_ao_mode", text="AO Routing")
        layout.prop(props, "pbr_import_preserve_existing", text="Preserve Other Nodes")

        layout.separator()
        layout.label(text="Active Preset Mapping", icon="SETTINGS")

        try:
            from core.pbr_presets import DEFAULT_PRESET_ID, PBRImporterPresetManager
        except (ImportError, ValueError):
            from ..core.pbr_presets import DEFAULT_PRESET_ID, PBRImporterPresetManager

        preset_id = getattr(props, "pbr_import_preset", "") or getattr(props, "pbr_preset", DEFAULT_PRESET_ID)
        try:
            preset = PBRImporterPresetManager.get_preset(preset_id)
            box = layout.box()
            box.label(text=preset.get("name", preset_id), icon="PRESET")
            desc = preset.get("description", "")
            if desc:
                box.label(text=desc)

            maps = preset.get("maps", [])
            col = box.column(align=True)
            for m in maps:
                suffixes_str = ", ".join(m.get("suffixes", [])[:4])
                if len(m.get("suffixes", [])) > 4:
                    suffixes_str += ", ..."
                row = col.row()
                row.label(text=m.get("name", m.get("id")), icon="LAYER_USED")
                row.label(text=f"({suffixes_str})")

            box.operator("lod_tool.reset_pbr_preset", text="Reset to Built-in Default", icon="LOOP_BACK")
        except Exception as exc:
            layout.label(text=f"Error loading preset: {exc}", icon="ERROR")


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

        layout.label(text="Transform & Modifiers", icon="OBJECT_ORIGIN")
        layout.operator("lod_tool.apply_transforms", text="Apply Scale & Rotation", icon="CHECKMARK")
        layout.operator("lod_tool.apply_all_modifiers", text="Bake / Apply Modifiers", icon="MODIFIER")

        layout.separator()
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


class OMNIMESH_PT_popover_bridge(Panel):
    """Popover for Live Engine Bridge connection settings."""

    bl_idname = "OMNIMESH_PT_popover_bridge"
    bl_label = "Live Bridge Settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 16

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = context.scene.lod_tool

        layout.label(text="Live Bridge Connection", icon="LINKED")
        layout.prop(props, "engine_project_path", text="Project Path")
        layout.prop(props, "enable_live_sync", text="Auto-Sync on Export")


POPOVER_CLASSES = (
    OMNIMESH_PT_popover_import,
    OMNIMESH_PT_popover_import_preset,
    OMNIMESH_PT_popover_sanitize,
    OMNIMESH_PT_popover_materials,
    OMNIMESH_PT_popover_collision,
    OMNIMESH_PT_popover_configure,
    OMNIMESH_PT_popover_generate,
    OMNIMESH_PT_popover_export,
    OMNIMESH_PT_popover_export_preset,
    OMNIMESH_PT_popover_bridge,
)
