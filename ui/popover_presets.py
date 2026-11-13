"""
OmniMesh Preset Configuration Popover Panels for Blender 5.0+ and 5.2 LTS.
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
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.types import Panel
else:
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
    from ..core.impostor_math import compute_impostor_atlas_resolution, normalize_impostor_grid_size
    from ..core.lod_presets import (
        DEFAULT_LOD_PRESET_ID,
        LODPresetManager,
    )
    from ..core.pbr_presets import (
        DEFAULT_PRESET_ID,
        PBRExportPresetManager,
        PBRImportPresetManager,
    )
    from .properties import sync_maps_from_preset
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
    from core.impostor_math import compute_impostor_atlas_resolution, normalize_impostor_grid_size
    from core.lod_presets import (
        DEFAULT_LOD_PRESET_ID,
        LODPresetManager,
    )
    from core.pbr_presets import (
        DEFAULT_PRESET_ID,
        PBRExportPresetManager,
        PBRImportPresetManager,
    )
    from ui.properties import sync_maps_from_preset
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
        if not bpy or not context or not self.layout:
            return
        layout = self.layout
        props = _get_popover_props(context)
        if not props:
            return

        preset_id = getattr(props, "engine_import_preset", "") or DEFAULT_ENGINE_IMPORT_PRESET_ID
        preset = EngineImportPresetManager.get_preset(preset_id)
        is_builtin = EngineImportPresetManager.is_builtin(preset_id)

        row_title = layout.row(align=True)
        row_title.label(text=preset.get("name", preset_id), icon="PRESET")
        if not is_builtin:
            row_title.operator("omnimesh.rename_engine_import_preset", text="", icon="GREASEPENCIL")

        if is_builtin:
            box_badge = layout.box()
            box_badge.label(text="Built-in Preset (Duplicate to save as custom)", icon="INFO")

        layout.separator()
        layout.label(text="Package Components to Ingest", icon="CHECKBOX_HLT")
        box_comp = layout.box()
        box_comp.prop(props, "engine_import_geometry", text="Geometry & Multi-LODs")
        box_comp.prop(props, "engine_import_spatial", text="Spatial Markers (Datum, CG, Wheels)")
        box_comp.prop(props, "engine_import_lights", text="Aviation Lights (Nav, Strobe, Landing)")
        box_comp.prop(props, "engine_import_cameras", text="Cameras (Pilot, Cockpit, External)")

        layout.separator()
        layout.label(text="Model Target Selection", icon="OUTLINER_OB_MESH")
        row_tgt = layout.row(align=True)
        row_tgt.prop(props, "engine_import_model_target", text="Target")

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
        if not bpy or not context or not self.layout:
            return
        layout = self.layout
        props = _get_popover_props(context)
        if not props:
            return

        preset_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID
        preset = PBRImportPresetManager.get_preset(preset_id)
        is_builtin = PBRImportPresetManager.is_builtin(preset_id)

        # Header: Name and small pencil rename icon for custom presets
        row_title = layout.row(align=True)
        row_title.label(text=preset.get("name", preset_id), icon="PRESET")
        if not is_builtin:
            row_title.operator("lod_tool.rename_import_preset", text="", icon="GREASEPENCIL")

        if is_builtin:
            box_badge = layout.box()
            box_badge.label(text="Built-in Template (Read-Only)", icon="LOCKED")

        layout.separator()
        layout.prop(props, "pbr_import_ao_mode", text="AO Routing")

        layout.separator()
        layout.label(text="Texture Map Rules & Suffixes", icon="NODE_MATERIAL")

        if len(props.pbr_active_maps) == 0:
            box_empty = layout.box()
            box_empty.label(text="Preset maps not initialized.", icon="INFO")
            box_empty.operator("lod_tool.init_preset_maps", text="Initialize Maps", icon="FILE_REFRESH")
            if bpy and hasattr(bpy, "app") and hasattr(bpy.app, "timers"):
                scene_name = getattr(context.scene, "name", "")

                def _deferred_init():
                    try:
                        sc = bpy.data.scenes.get(scene_name) if scene_name and hasattr(bpy, "data") else None
                        p_obj = getattr(sc, "lod_tool", None) if sc else None
                        if p_obj and len(getattr(p_obj, "pbr_active_maps", [])) == 0:
                            p_id = getattr(p_obj, "pbr_import_preset", "") or DEFAULT_PRESET_ID
                            p_data = PBRImportPresetManager.get_preset(p_id)
                            sync_maps_from_preset(p_obj, p_data)
                    except Exception as exc:
                        logger.debug("Deferred preset map hydration skipped: %s", exc)

                bpy.app.timers.register(_deferred_init, first_interval=0.001)
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
        sub_add_tpl = col_btn.column(align=True)
        sub_add_tpl.enabled = not is_builtin
        sub_add_tpl.operator("lod_tool.add_map_template", icon="PRESET_NEW", text="")
        sub_add = col_btn.column(align=True)
        sub_add.enabled = not is_builtin
        sub_add.operator("lod_tool.add_preset_map", icon="ADD", text="")
        sub_rem = col_btn.column(align=True)
        sub_rem.enabled = len(props.pbr_active_maps) > 1 and not is_builtin
        sub_rem.operator("lod_tool.delete_preset_map", icon="REMOVE", text="")
        col_btn.separator()
        sub_up = col_btn.column(align=True)
        sub_up.enabled = not is_builtin
        op_up = sub_up.operator("lod_tool.move_preset_map", icon="TRIA_UP", text="")
        if op_up is not None:
            op_up.direction = "UP"
        sub_down = col_btn.column(align=True)
        sub_down.enabled = not is_builtin
        op_down = sub_down.operator("lod_tool.move_preset_map", icon="TRIA_DOWN", text="")
        if op_down is not None:
            op_down.direction = "DOWN"

        maps = props.pbr_active_maps
        idx = props.pbr_active_map_index
        if 0 <= idx < len(maps):
            active_map = maps[idx]
            box_detail = layout.box()
            box_detail.enabled = not is_builtin
            col = box_detail.column(align=True)
            col.prop(active_map, "name", text="Map Name")
            col.prop(active_map, "suffixes_str", text="Suffixes")

            col.prop(active_map, "color_space", text="Color Space")

            col.prop(active_map, "is_normal_map", text="Is Normal Map")
            if active_map.is_normal_map:
                col.prop(active_map, "normal_format", text="Normal Format")

            col.separator()
            col.prop(active_map, "is_packed", text="Packed (R/G/B/A)")

            if not active_map.is_packed:
                row_rgb = col.row(align=True)
                row_rgb.prop(active_map, "target_rgb", text="Target Socket")
                row_rgb.prop(active_map, "invert_rgb", text="Invert")
                row_a = col.row(align=True)
                row_a.prop(active_map, "target_a", text="Alpha / Opacity")
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
    bl_ui_units_x = 18

    def draw(self, context: Any) -> None:
        if not bpy or not context or not self.layout:
            return
        layout = self.layout
        props = _get_popover_props(context)
        cfg_props = getattr(props, "config_presets", None) if props else None
        if not cfg_props:
            return

        preset_id = getattr(cfg_props, "config_preset", "") or DEFAULT_CONFIG_PRESET_ID
        preset = ConfigPresetManager.get_preset(preset_id)
        is_builtin = ConfigPresetManager.is_builtin(preset_id)

        row_title = layout.row(align=True)
        row_title.label(text=preset.get("name", preset_id), icon="PRESET")
        if not is_builtin:
            row_title.operator("omnimesh.rename_config_preset", text="", icon="GREASEPENCIL")

        if is_builtin:
            box_badge = layout.box()
            box_badge.label(text="Built-in Template (Read-Only)", icon="LOCKED")

        layout.separator()
        layout.label(text="Categories to Include", icon="CHECKBOX_HLT")
        box_comp = layout.box()
        box_comp.enabled = not is_builtin
        box_comp.prop(cfg_props, "include_spatial", text="Spatial & Wheels")
        box_comp.prop(cfg_props, "include_lights", text="Aviation Lights")
        box_comp.prop(cfg_props, "include_cameras", text="Cockpit & Cameras")
        box_comp.prop(cfg_props, "include_exits", text="Exits & Doors")
        box_comp.prop(cfg_props, "include_engines", text="Engines & Props")
        box_comp.prop(cfg_props, "include_interactions", text="Interaction & Clickspots")


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
        if not bpy or not context or not self.layout:
            return
        layout = self.layout
        props = _get_popover_props(context)
        if not props:
            return

        preset_id = getattr(props, "lod_preset", "") or DEFAULT_LOD_PRESET_ID
        preset = LODPresetManager.get_preset(preset_id)
        is_builtin = LODPresetManager.is_builtin(preset_id)

        # 1. Header & Preset Management
        row_title = layout.row(align=True)
        row_title.label(text=preset.get("name", preset_id), icon="PRESET")
        if not is_builtin:
            row_title.operator("lod_tool.rename_lod_preset", text="", icon="GREASEPENCIL")

        if is_builtin:
            box_badge = layout.box()
            box_badge.label(text="Built-in Template (Read-Only)", icon="LOCKED")

        layout.separator()
        layout.prop(props, "tau_sse", slider=True, text="Visual Stability (τ)")

        layout.separator()

        # 2. Preset Tiers (Compact Overview)
        row_hdr = layout.row(align=True)
        row_hdr.label(text="Preset Tiers & Budgets", icon="MESH_DATA")

        row = layout.row()
        row.enabled = not is_builtin
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
        sub_rem.enabled = len(props.lod_preset_active_tiers) > 1 and not is_builtin
        sub_rem.operator("lod_tool.remove_preset_tier", icon="REMOVE", text="")

        # Cull Screen Size threshold immediately beneath the tiers
        row_cull = layout.row(align=True)
        row_cull.enabled = not is_builtin
        row_cull.prop(props, "cull_screen_size_pct", slider=True, text="Cull at Screen Size")

        layout.separator()

        # 3. Hierarchy & Draw-Calls
        box_hier = layout.box()
        box_hier.enabled = not is_builtin
        box_hier.use_property_split = True
        box_hier.use_property_decorate = False
        box_hier.prop(props, "consolidate_hierarchy", text="Consolidate Hierarchy")

        # 4. Occlusion & Slender Culling
        box_cull = layout.box()
        box_cull.enabled = not is_builtin
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
        box_chunk.enabled = not is_builtin
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
        box_imp.enabled = not is_builtin
        box_imp.use_property_split = True
        box_imp.use_property_decorate = False
        box_imp.label(text="Billboard Impostor", icon="IMAGE_PLANE")
        box_imp.prop(props, "enable_impostor_lod", text="Enable Impostor")
        if props.enable_impostor_lod:
            draw_impostor_configuration_fields(box_imp, props)


def draw_impostor_configuration_fields(box: Any, props: Any) -> None:
    """Draws shared Billboard & Octahedral Impostor configuration controls."""
    box.prop(props, "impostor_mode", text="Mode")

    lods_val = getattr(props, "lods", [])
    try:
        raw_spct = lods_val[-1].screen_size_pct if len(lods_val) > 0 else 5.0
        s_pct = float(raw_spct) if isinstance(raw_spct, (int, float)) and not isinstance(raw_spct, bool) else 5.0
    except (TypeError, IndexError, AttributeError):
        s_pct = 5.0

    auto_res = bool(getattr(props, "auto_impostor_resolution", True))
    raw_res = getattr(props, "impostor_resolution", "2048")
    conf_res: str | int = raw_res if isinstance(raw_res, (str, int)) and not isinstance(raw_res, bool) else "2048"
    calc_res = compute_impostor_atlas_resolution(auto_res, conf_res, s_pct)

    mode_str = str(getattr(props, "impostor_mode", "ORTHO_3_AXES"))
    if "OCTA" in mode_str:
        box.prop(props, "impostor_render_underside", text="Render Underside")
        box.prop(props, "impostor_grid_size", text="Frames (N×N)")
        raw_grid = getattr(props, "impostor_grid_size", 8)
        grid_size = (
            normalize_impostor_grid_size(raw_grid)
            if isinstance(raw_grid, int) and not isinstance(raw_grid, bool)
            else 8
        )
        tile_px = max(1, calc_res // grid_size)
        row_grid = box.row()
        row_grid.label(
            text=f"Views: {grid_size * grid_size} ({grid_size}×{grid_size})  •  {tile_px}px/tile", icon="GRID"
        )

    box.prop(props, "auto_impostor_resolution", text="Auto Resolution")
    if not auto_res:
        box.prop(props, "impostor_resolution", text="Resolution")
    else:
        row_calc = box.row()
        row_calc.label(text=f"Calculated: {calc_res}×{calc_res}", icon="INFO")

    box.prop(props, "impostor_replace_last_lod", text="Final LOD Tier")


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
        if not bpy or not context or not self.layout:
            return
        layout = self.layout
        props = _get_popover_props(context)
        if not props:
            return

        preset_id = getattr(props, "pbr_export_preset", "") or DEFAULT_PRESET_ID
        preset = PBRExportPresetManager.get_preset(preset_id)
        is_builtin = PBRExportPresetManager.is_builtin(preset_id)

        row_title = layout.row(align=True)
        row_title.label(text=preset.get("name", preset_id), icon="PRESET")
        if not is_builtin:
            row_title.operator("lod_tool.rename_export_preset", text="", icon="GREASEPENCIL")

        if is_builtin:
            box_badge = layout.box()
            box_badge.label(text="Built-in Template (Read-Only)", icon="LOCKED")

        layout.separator()
        layout.label(text="Preset Configuration", icon="SETTINGS")
        col_cfg = layout.column(align=True)
        col_cfg.enabled = not is_builtin
        col_cfg.prop(props, "target_engine", text="Target Engine")
        col_cfg.prop(props, "pbr_export_texture_strategy", text="Strategy")
        if props.pbr_export_texture_strategy in {"SMART_AUTO", "BAKE"}:
            col_cfg.prop(props, "texture_max_resolution", text="Bake Resolution")
        col_cfg.prop(props, "pbr_export_bit_depth", text="Bit Depth")
        col_cfg.prop(props, "pbr_export_naming_pattern", text="Naming Pattern")

        layout.separator()
        layout.label(text="Package Pipeline Toggles", icon="PACKAGE")
        layout.prop(props, "export_packed_textures", text="Pack PBR Textures on Export")
        layout.prop(props, "bake_animations", text="Bake Skeletal Animations")

        # MSFS SDK Options Box
        if getattr(props, "target_engine", "") == "MSFS_2024":
            layout.separator()
            box_msfs_opts = layout.box()
            box_msfs_opts.use_property_split = True
            box_msfs_opts.use_property_decorate = False
            box_msfs_opts.label(text="MSFS SDK Options", icon="PREFERENCES")
            box_msfs_opts.prop(props, "msfs_export_full_package", text="Export Full Package")
            box_msfs_opts.prop(props, "msfs_preserve_decals", text="Preserve Decals")

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
            box_empty.operator("lod_tool.init_preset_maps", text="Initialize Maps", icon="FILE_REFRESH")
            return

        row = layout.row()
        row.template_list(
            "OMNIMESH_UL_export_preset_maps",
            "",
            props,
            "pbr_export_active_maps",
            props,
            "pbr_export_active_map_index",
            rows=min(max(len(props.pbr_export_active_maps), 4), 7),
        )
        col_btn = row.column(align=True)
        sub_add_tpl = col_btn.column(align=True)
        sub_add_tpl.enabled = not is_builtin
        sub_add_tpl.operator("lod_tool.add_export_map_template", icon="PRESET_NEW", text="")
        sub_add = col_btn.column(align=True)
        sub_add.enabled = not is_builtin
        sub_add.operator("lod_tool.add_export_preset_map", icon="ADD", text="")
        sub_rem = col_btn.column(align=True)
        sub_rem.enabled = len(props.pbr_export_active_maps) > 1 and not is_builtin
        sub_rem.operator("lod_tool.delete_export_preset_map", icon="REMOVE", text="")
        col_btn.separator()
        sub_up = col_btn.column(align=True)
        sub_up.enabled = not is_builtin
        op_up = sub_up.operator("lod_tool.move_export_preset_map", icon="TRIA_UP", text="")
        if op_up is not None:
            op_up.direction = "UP"
        sub_down = col_btn.column(align=True)
        sub_down.enabled = not is_builtin
        op_down = sub_down.operator("lod_tool.move_export_preset_map", icon="TRIA_DOWN", text="")
        if op_down is not None:
            op_down.direction = "DOWN"

        # Detail box for selected map
        idx = props.pbr_export_active_map_index
        if 0 <= idx < len(props.pbr_export_active_maps):
            active_map = props.pbr_export_active_maps[idx]
            box = layout.box()
            box.enabled = not is_builtin
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

            box.prop(active_map, "is_packed", text="Packed (R/G/B/A)")

            col = box.column(align=True)
            if not active_map.is_packed:
                row_rgb = col.row(align=True)
                row_rgb.prop(active_map, "target_rgb", text="Target Socket")
                row_rgb.prop(active_map, "invert_rgb", text="Invert")
                row_a = col.row(align=True)
                row_a.prop(active_map, "target_a", text="Alpha / Opacity")
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
