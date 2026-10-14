"""
OmniMesh Preset Configuration Popover Panels for Blender 4.2+ and 5.2 LTS.
Dedicated popovers for managing and customizing presets:
- Config Presets (Aircraft/Vehicle Feature Spawn Rules)
- Engine Import Presets (MSFS Project Ingestion Rules)
- PBR Import Presets (Texture Map Matching & Suffix Rules)
- LOD Presets (Quality Curves, Tiers & Decimation Heuristics)
- Export Presets (Channel Packing, Bit Depth, Naming & MSFS SDK Options)

Design Invariants:
- Omit `bl_category` to prevent ghost tabs in the N-Panel.
- Omit `bl_parent_id` to prevent accordion collision.
- Declare `bl_ui_units_x = 22` (or 16-20) to prevent label/slider truncation in popups.
- RNA Mutation Ban: Never mutate RNA collections or properties inside draw().
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
    from ..core.config_presets import (
        DEFAULT_CONFIG_PRESET_ID,
        ConfigPresetManager,
    )
    from ..core.engine_import_presets import (
        DEFAULT_ENGINE_IMPORT_PRESET_ID,
        EngineImportPresetManager,
    )
    from ..core.lod_presets import (
        DEFAULT_LOD_PRESET_ID,
        LODPresetManager,
    )
    from ..core.pbr_presets import (
        DEFAULT_PRESET_ID,
        PBRExportPresetManager,
        PBRImportPresetManager,
    )
    from .utils import _get_popover_props
except (ImportError, ValueError):
    from core.config_presets import (
        DEFAULT_CONFIG_PRESET_ID,
        ConfigPresetManager,
    )
    from core.engine_import_presets import (
        DEFAULT_ENGINE_IMPORT_PRESET_ID,
        EngineImportPresetManager,
    )
    from core.lod_presets import (
        DEFAULT_LOD_PRESET_ID,
        LODPresetManager,
    )
    from core.pbr_presets import (
        DEFAULT_PRESET_ID,
        PBRExportPresetManager,
        PBRImportPresetManager,
    )
    from ui.utils import _get_popover_props


# =========================================================================
# 1. ENGINE IMPORT PRESET POPOVER
# =========================================================================


class OMNIMESH_PT_popover_engine_import_preset(Panel):
    """Popover for configuring engine project package import options."""

    bl_idname = "OMNIMESH_PT_popover_engine_import_preset"
    bl_label = "Engine Import Settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 20

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = _get_popover_props(context)
        if not props:
            return

        preset_id = getattr(props, "engine_import_preset", "") or DEFAULT_ENGINE_IMPORT_PRESET_ID
        preset = EngineImportPresetManager.get_preset(preset_id)
        is_builtin = EngineImportPresetManager.is_builtin(preset_id)

        layout.label(text=preset.get("name", preset_id), icon="PACKAGE")
        desc = preset.get("description", "")
        if desc:
            layout.label(text=desc)

        # Preset Management Row
        row_act = layout.row(align=True)
        row_act.operator("omnimesh.duplicate_engine_import_preset", text="Duplicate", icon="DUPLICATE")
        sub_del = row_act.row(align=True)
        sub_del.enabled = not is_builtin
        sub_del.operator("omnimesh.delete_engine_import_preset", text="Delete", icon="X")
        row_act.operator("omnimesh.convert_asobo_hierarchy", text="Convert x0..x6", icon="OUTLINER_COLLECTION")

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


# =========================================================================
# 2. PBR IMPORT PRESET POPOVER
# =========================================================================


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
        props = _get_popover_props(context)
        if not props:
            return

        preset_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID
        preset = PBRImportPresetManager.get_preset(preset_id)
        is_builtin = PBRImportPresetManager.is_builtin(preset_id)

        layout.label(text=preset.get("name", preset_id), icon="PRESET")
        desc = preset.get("description", "")
        if desc:
            layout.label(text=desc)

        # Preset Management Row
        row_act = layout.row(align=True)
        op_dup = row_act.operator("lod_tool.duplicate_preset", text="Duplicate", icon="DUPLICATE")
        op_dup.preset_type = "IMPORT"
        sub_del = row_act.row(align=True)
        sub_del.enabled = not is_builtin
        sub_del.operator("lod_tool.delete_import_preset", text="Delete", icon="X")

        layout.separator()
        layout.label(text="Texture Path & Routing", icon="IMAGE_DATA")
        layout.prop(props, "pbr_import_path_mode", text="Path Mode")
        layout.prop(props, "pbr_import_ao_mode", text="AO Routing")
        layout.prop(props, "pbr_import_preserve_existing", text="Preserve Other Nodes")

        layout.separator()
        layout.label(text="Texture Map Rules", icon="NODE_MATERIAL")

        if len(props.pbr_active_maps) == 0:
            box_empty = layout.box()
            box_empty.label(text="Preset maps not initialized.", icon="INFO")
            return

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


# =========================================================================
# 3. CONFIG PRESET POPOVER
# =========================================================================


class OMNIMESH_PT_popover_config_preset(Panel):
    """Popover for config preset component filters and options."""

    bl_label = "Config Preset Settings"
    bl_idname = "OMNIMESH_PT_popover_config_preset"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 16

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        props = _get_popover_props(context)
        cfg_props = getattr(props, "config_presets", None) if props else None
        if not cfg_props:
            return

        preset_id = getattr(cfg_props, "config_preset", "") or DEFAULT_CONFIG_PRESET_ID
        preset = ConfigPresetManager.get_preset(preset_id)
        is_builtin = ConfigPresetManager.is_builtin(preset_id)

        layout.label(text=preset.get("name", preset_id), icon="PRESET")
        desc = preset.get("description", "")
        if desc:
            layout.label(text=desc)

        # Preset Management Row
        row_act = layout.row(align=True)
        row_act.operator("omnimesh.duplicate_config_preset", text="Duplicate", icon="DUPLICATE")
        sub_del = row_act.row(align=True)
        sub_del.enabled = not is_builtin
        sub_del.operator("omnimesh.delete_config_preset", text="Delete", icon="X")

        layout.separator()
        layout.label(text="Categories to Include", icon="CHECKBOX_HLT")
        box_comp = layout.box()
        box_comp.prop(cfg_props, "include_spatial", text="Spatial & Wheels")
        box_comp.prop(cfg_props, "include_lights", text="Aviation Lights")
        box_comp.prop(cfg_props, "include_cameras", text="Cockpit & Cameras")
        box_comp.prop(cfg_props, "include_exits", text="Exits & Doors")
        box_comp.prop(cfg_props, "include_engines", text="Engines & Props")


# =========================================================================
# 4. LOD PRESET POPOVER
# =========================================================================


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
        props = _get_popover_props(context)
        if not props:
            return

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
                box_chunk.prop(props, "enable_hierarchical_hlod", text="Hierarchical (Quadtree)")
                box_chunk.prop(props, "hlod_start_tier", text="HLOD Start Tier")
                box_chunk.prop(props, "hlod_proxy_remesh", text="Terminal Voxel Wrap")
                if props.hlod_proxy_remesh:
                    box_chunk.prop(props, "hlod_proxy_voxel_size", text="Voxel Shell Size (m)")

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
                s_pct = props.lods[-1].screen_size_pct if len(props.lods) > 0 else 5.0
                target_px = max(256, min(4096, int(2048 * (s_pct / 10.0))))
                calc_res = 1 << (target_px - 1).bit_length()
                calc_res = max(256, min(4096, calc_res))
                row_calc = box_imp.row()
                row_calc.label(text=f"Calculated: {calc_res}×{calc_res}", icon="INFO")

        layout.separator()
        row_act = layout.row(align=True)
        row_act.operator("lod_tool.reset_to_preset", text="Reset to Factory", icon="LOOP_BACK")
        op_dup = row_act.operator("lod_tool.duplicate_preset", text="Duplicate", icon="DUPLICATE")
        op_dup.preset_type = "LOD"
        if LODPresetManager.is_user_preset(preset_id):
            row_act.operator("lod_tool.delete_lod_preset", text="Delete Preset", icon="TRASH")


# =========================================================================
# 5. PBR EXPORT PRESET POPOVER
# =========================================================================


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
        props = _get_popover_props(context)
        if not props:
            return

        preset_id = getattr(props, "pbr_export_preset", "") or DEFAULT_PRESET_ID
        preset = PBRExportPresetManager.get_preset(preset_id)
        is_builtin = PBRExportPresetManager.is_builtin(preset_id)

        layout.label(text=preset.get("name", preset_id), icon="PRESET")
        desc = preset.get("description", "")
        if desc:
            layout.label(text=desc)

        # Preset Management Row
        row_act = layout.row(align=True)
        op_dup = row_act.operator("lod_tool.duplicate_preset", text="Duplicate", icon="DUPLICATE")
        op_dup.preset_type = "EXPORT"
        sub_del = row_act.row(align=True)
        sub_del.enabled = not is_builtin
        sub_del.operator("lod_tool.delete_export_preset", text="Delete", icon="X")

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

        # MSFS SDK Options Box
        if getattr(props, "target_engine", "") == "MSFS_2024":
            layout.separator()
            box_msfs_opts = layout.box()
            box_msfs_opts.use_property_split = True
            box_msfs_opts.use_property_decorate = False
            box_msfs_opts.label(text="MSFS SDK Options", icon="PREFERENCES")
            box_msfs_opts.prop(props, "msfs_export_full_package", text="Export Full Package")
            box_msfs_opts.prop(props, "msfs_target_version", text="Target SDK")
            box_msfs_opts.prop(props, "msfs_preserve_decals", text="Preserve Decals")

            if getattr(props, "msfs_target_version", "2024") == "2024":
                box_opts_2024 = box_msfs_opts.box()
                box_opts_2024.label(text="[model.options] (MSFS 2024)", icon="FILE_TEXT")
                box_opts_2024.prop(props, "msfs_with_exterior_show_interior", text="Show Interior")
                box_opts_2024.prop(props, "msfs_with_exterior_show_interior_hide_first_lod", text="Hide First LOD Int")
                box_opts_2024.prop(props, "msfs_with_interior_force_first_lod", text="Force First LOD Int")
                box_opts_2024.prop(props, "msfs_with_interior_show_exterior", text="Show Exterior")

        layout.separator()
        layout.label(text="Export Maps & Channel Routing", icon="NODE_MATERIAL")

        if len(props.pbr_export_active_maps) == 0:
            box_empty = layout.box()
            box_empty.label(text="Export maps not initialized.", icon="INFO")
            return

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


PRESET_POPOVER_CLASSES = (
    OMNIMESH_PT_popover_config_preset,
    OMNIMESH_PT_popover_engine_import_preset,
    OMNIMESH_PT_popover_import_preset,
    OMNIMESH_PT_popover_lod_preset,
    OMNIMESH_PT_popover_export_preset,
)

__all__ = [
    "OMNIMESH_PT_popover_config_preset",
    "OMNIMESH_PT_popover_engine_import_preset",
    "OMNIMESH_PT_popover_import_preset",
    "OMNIMESH_PT_popover_lod_preset",
    "OMNIMESH_PT_popover_export_preset",
    "PRESET_POPOVER_CLASSES",
]
