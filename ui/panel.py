"""
OmniMesh Unified Single-Panel Architecture for Blender 5.0+ and 5.2 LTS.
Integrates all workflow stages into a single panel with a vertical icon navigation bar:
- 1. Import (Engine Project & PBR Texture Set Importer)
- 2. Add (Vehicle & Asset Configuration Presets, Impostors, Colliders & Clickspots)
- 3. Modify (Base Prep, Sanitization, Modifiers, Materials, Chunking & Voxel Remesh)
- 4. LODs (Tier Configuration, Compact Responsive Cards, Decimation & Testing)
- 5. Engine Export (Multi-Engine Package Export)
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
    from ..core.config_presets import DEFAULT_CONFIG_PRESET_ID, ConfigPresetManager
    from ..core.engine_import_presets import DEFAULT_ENGINE_IMPORT_PRESET_ID, EngineImportPresetManager
    from ..core.lod_presets import DEFAULT_LOD_PRESET_ID, LODPresetManager
    from ..core.pbr_presets import DEFAULT_PRESET_ID, PBRExportPresetManager, PBRImportPresetManager
    from .operators import resolve_lod_context
    from .panel_helpers import draw_vehicle_helpers
    from .popovers import POPOVER_CLASSES
    from .utils import get_asset_base_meshes, get_available_asset_names, is_object_valid, resolve_effective_asset_name
except (ImportError, ValueError):
    from core.config_presets import DEFAULT_CONFIG_PRESET_ID, ConfigPresetManager
    from core.engine_import_presets import DEFAULT_ENGINE_IMPORT_PRESET_ID, EngineImportPresetManager
    from core.lod_presets import DEFAULT_LOD_PRESET_ID, LODPresetManager
    from core.pbr_presets import DEFAULT_PRESET_ID, PBRExportPresetManager, PBRImportPresetManager
    from ui.operators import resolve_lod_context
    from ui.panel_helpers import draw_vehicle_helpers
    from ui.popovers import POPOVER_CLASSES
    from ui.utils import get_asset_base_meshes, get_available_asset_names, is_object_valid, resolve_effective_asset_name


# Tab Drawers


def _draw_tab_import(layout: Any, context: Any, props: Any) -> None:
    box_engine = layout.box()
    box_engine.label(text="Model Importer", icon="PACKAGE")

    eng_preset_id = getattr(props, "engine_import_preset", "") or DEFAULT_ENGINE_IMPORT_PRESET_ID
    is_builtin_eng = EngineImportPresetManager.is_builtin(eng_preset_id)

    row_eng_preset = box_engine.row(align=True)
    row_eng_preset.use_property_split = False
    row_eng_preset.prop(props, "engine_import_preset", text="Preset")
    row_eng_preset.popover(panel="OMNIMESH_PT_popover_engine_import_preset", icon="PREFERENCES", text="")
    row_eng_preset.operator("omnimesh.duplicate_engine_import_preset", text="", icon="DUPLICATE")
    sub_del_eng = row_eng_preset.row(align=True)
    sub_del_eng.enabled = not is_builtin_eng
    sub_del_eng.operator("omnimesh.delete_engine_import_preset", text="", icon="X")

    row_eng_act = box_engine.row(align=True)
    row_eng_act.use_property_split = False
    row_eng_act.scale_y = 1.2
    row_eng_act.operator("omnimesh.import_engine_project", text="Import Model", icon="IMPORT")

    if props.last_engine_import_summary:
        box_engine.label(text=props.last_engine_import_summary, icon="CHECKMARK")

    box_pbr = layout.box()
    box_pbr.label(text="PBR Texture Set Importer", icon="IMAGE_DATA")

    pbr_preset_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID
    is_builtin_pbr = PBRImportPresetManager.is_builtin(pbr_preset_id)

    row_preset = box_pbr.row(align=True)
    row_preset.use_property_split = False
    row_preset.prop(props, "pbr_import_preset", text="Preset")
    row_preset.popover(panel="OMNIMESH_PT_popover_import_preset", icon="PREFERENCES", text="")
    op_dup_pbr = row_preset.operator("lod_tool.duplicate_preset", text="", icon="DUPLICATE")
    if op_dup_pbr is not None:
        op_dup_pbr.preset_type = "IMPORT"
    sub_del_pbr = row_preset.row(align=True)
    sub_del_pbr.enabled = not is_builtin_pbr
    sub_del_pbr.operator("lod_tool.delete_import_preset", text="", icon="X")

    row_btn = box_pbr.row(align=True)
    row_btn.use_property_split = False
    row_btn.scale_y = 1.2
    row_btn.operator("lod_tool.import_pbr_set", text="Import PBR Textures", icon="IMPORT")

    if getattr(props, "last_pbr_import_summary", ""):
        box_pbr.label(text=props.last_pbr_import_summary, icon="CHECKMARK")


# Tab 2: Modify & Add Features


def _draw_tab_add(layout: Any, context: Any, props: Any) -> None:
    """Draw vehicle config, impostors, colliders, and interaction features."""
    box_gen = layout.box()
    box_gen.label(text="Generate", icon="MODIFIER")

    row_imp = box_gen.row(align=True)
    row_imp.use_property_split = False
    row_imp.scale_y = 1.2
    row_imp.operator("lod_tool.generate_impostor", text="Impostor", icon="IMAGE_PLANE")
    row_imp.popover(panel="OMNIMESH_PT_popover_impostor", icon="PREFERENCES", text="")

    row_col = box_gen.row(align=True)
    row_col.use_property_split = False
    row_col.scale_y = 1.2
    row_col.operator("lod_tool.generate_collision_hulls", text="Colliders", icon="MOD_PHYSICS")
    row_col.popover(panel="OMNIMESH_PT_popover_collision", icon="PREFERENCES", text="")

    cfg_props = getattr(props, "config_presets", None)
    if cfg_props:
        box_cfg = layout.box()
        box_cfg.label(text="Vehicle & Asset Configurator", icon="PRESET")

        cfg_id = getattr(cfg_props, "config_preset", "") or DEFAULT_CONFIG_PRESET_ID
        cfg_is_builtin = ConfigPresetManager.is_builtin(cfg_id)

        row_cfg_p = box_cfg.row(align=True)
        row_cfg_p.use_property_split = False
        row_cfg_p.prop(cfg_props, "config_preset", text="Preset")
        row_cfg_p.popover(panel="OMNIMESH_PT_popover_config_preset", icon="PREFERENCES", text="")
        row_cfg_p.operator("omnimesh.duplicate_config_preset", text="", icon="DUPLICATE")
        sub_del_cfg = row_cfg_p.row(align=True)
        sub_del_cfg.enabled = not cfg_is_builtin
        sub_del_cfg.operator("omnimesh.delete_config_preset", text="", icon="X")

        row_cfg_act = box_cfg.row(align=True)
        row_cfg_act.use_property_split = False
        row_cfg_act.scale_y = 1.2
        row_cfg_act.operator("omnimesh.add_config_preset", text="Add Features", icon="ADD")

        if cfg_props.last_spawn_summary:
            box_cfg.label(text=cfg_props.last_spawn_summary, icon="CHECKMARK")

        draw_vehicle_helpers(box_cfg, cfg_props)

    int_props = getattr(props, "interaction", None)
    if int_props:
        box_int = layout.box()
        box_int.label(text="Interaction Trigger / Clickspots", icon="GIZMO")
        row_role = box_int.row(align=True)
        row_role.use_property_split = False
        row_role.prop(int_props, "role", text="Role")
        row_shape = box_int.row(align=True)
        row_shape.use_property_split = False
        row_shape.prop(int_props, "shape", text="Shape")
        row_int_act = box_int.row(align=True)
        row_int_act.use_property_split = False
        row_int_act.scale_y = 1.2
        row_int_act.operator("omnimesh.add_interaction_volume", text="Add Clickspot / Trigger", icon="ADD")


def _draw_tab_modify(layout: Any, context: Any, props: Any) -> None:
    """Draw complete Modify & Preparation workflow tab."""
    # 1. Mesh & Material Cleanup Card
    box_clean = layout.box()
    box_clean.label(text="Mesh & Material Cleanup", icon="BRUSH_DATA")

    row_san = box_clean.row(align=True)
    row_san.use_property_split = False
    row_san.scale_y = 1.2
    row_san.operator("lod_tool.clean_and_repair_mesh", text="Clean Mesh", icon="BRUSH_DATA")
    row_san.popover(panel="OMNIMESH_PT_popover_sanitize", icon="PREFERENCES", text="")

    row_mat = box_clean.row(align=True)
    row_mat.use_property_split = False
    row_mat.scale_y = 1.2
    row_mat.operator("lod_tool.clean_and_repair_materials", text="Clean Materials", icon="MATERIAL_DATA")
    row_mat.popover(panel="OMNIMESH_PT_popover_materials", icon="PREFERENCES", text="")

    # 2. Impostors, Colliders, Vehicle Config & Interaction Features
    _draw_tab_add(layout, context, props)

    # 3. Spatial Chunking Card
    box_chunk = layout.box()
    box_chunk.label(text="Spatial Chunking (Large Assets)", icon="MESH_GRID")
    row_chk_cell = box_chunk.row(align=True)
    row_chk_cell.use_property_split = False
    row_chk_cell.prop(props, "chunk_cell_size", text="Cell (m)")
    row_chk_mode = box_chunk.row(align=True)
    row_chk_mode.use_property_split = False
    row_chk_mode.prop(props, "chunk_partitioning_mode", text="Mode")
    row_chk_act = box_chunk.row(align=True)
    row_chk_act.use_property_split = False
    row_chk_act.scale_y = 1.2
    row_chk_act.operator("lod_tool.spatial_chunk_and_generate", text="Partition & Chunk LOD0", icon="MESH_GRID")


# Tab 4: LODs


def _draw_selection_banners(layout: Any, context: Any) -> None:
    sel_objs = getattr(context, "selected_objects", []) or []
    sel_meshes = [o for o in sel_objs if is_object_valid(o) and getattr(o, "type", "") == "MESH"]
    if len(sel_meshes) > 1:
        row_sync = layout.row(align=True)
        row_sync.operator(
            "lod_tool.sync_selection_settings",
            text=f"Sync Settings to Selection ({len(sel_meshes)} meshes)",
            icon="COMMUNITY",
        )

    active_obj = getattr(context, "active_object", None)
    if active_obj and is_object_valid(active_obj):
        lod_tool = getattr(active_obj, "lod_tool", None)
        if lod_tool:
            root_val = getattr(lod_tool, "lod_root_object", None)
            if root_val and (getattr(lod_tool, "is_generated_lod", False) or "_LOD" in getattr(active_obj, "name", "")):
                root_name = root_val.name if is_object_valid(root_val) else str(root_val)
                row_nav = layout.row(align=True)
                row_nav.label(text=f"Sub-LOD of '{root_name}'", icon="LINKED")
                row_nav.operator("lod_tool.select_master_asset", text="Select Master", icon="RESTRICT_SELECT_OFF")


def _calculate_base_tris(context: Any, props: Any, active_obj: Any) -> int:
    base_tris = getattr(props, "base_triangles", 0) or getattr(props, "last_generated_base_tris", 0)
    if isinstance(base_tris, (int, float)) and base_tris > 0:
        return int(base_tris)
    effective_asset = resolve_effective_asset_name(context, props)
    meshes = get_asset_base_meshes(context, effective_asset) if effective_asset else []
    if not meshes and active_obj and getattr(active_obj, "type", "") == "MESH":
        meshes = [active_obj]
    total_tris = 0
    for m in meshes:
        mesh_data = getattr(m, "data", None)
        if not mesh_data or not hasattr(mesh_data, "polygons"):
            continue
        if hasattr(mesh_data, "loops"):
            total_tris += max(0, len(mesh_data.loops) - 2 * len(mesh_data.polygons))
        else:
            total_tris += sum(len(p.vertices) - 2 for p in mesh_data.polygons)
    return total_tris


def _calculate_base_materials(context: Any, props: Any, active_obj: Any) -> int:
    effective_asset = resolve_effective_asset_name(context, props)
    meshes = get_asset_base_meshes(context, effective_asset) if effective_asset else []
    if not meshes and active_obj and getattr(active_obj, "type", "") == "MESH":
        meshes = [active_obj]
    mats = {s.material for m in meshes for s in getattr(m, "material_slots", []) if getattr(s, "material", None)}
    return len(mats)


def _draw_lod_card(box_lod: Any, tier: Any, idx: int, base_tris: int, base_mats: int, total_tiers: int) -> bool:
    card = box_lod.box()
    card.use_property_split = False

    row_hdr = card.row(align=True)
    if idx > 0:
        show_det = bool(getattr(tier, "show_details", False))
        arrow_icon = "TRIA_DOWN" if show_det else "TRIA_RIGHT"
        row_hdr.prop(tier, "show_details", text="", icon=arrow_icon, emboss=False)

    tier_name = getattr(tier, "name", f"LOD{idx}")
    actual_t = getattr(tier, "actual_tris", 0)

    raw_mats = getattr(tier, "mat_slots_count", 0)
    mat_slots = int(raw_mats) if isinstance(raw_mats, (int, float)) else 0
    if getattr(tier, "is_impostor", False):
        mat_count = mat_slots or 1
    elif mat_slots > 0:
        mat_count = mat_slots
    else:
        mat_count = base_mats
    mat_suffix = f"  •  {mat_count} mat" if mat_count == 1 else f"  •  {mat_count} mats"

    is_out_of_sync = False
    last_target = getattr(tier, "last_baked_target_pct", -1.0)
    if idx == 0:
        state = "SOURCE"
    elif last_target > 0.0 and abs(tier.target_tris_pct - last_target) > 0.01:
        state = "OUT_OF_SYNC"
        is_out_of_sync = True
    elif actual_t > 0:
        state = "BAKED"
    else:
        state = "PLANNED"

    if getattr(tier, "is_impostor", False):
        row_hdr.label(text=f"{tier_name} (Impostor){mat_suffix}", icon="IMAGE_DATA")
    elif actual_t > 0:
        row_hdr.label(text=f"{tier_name}  •  {actual_t:,} tris{mat_suffix}", icon="MESH_DATA")
    else:
        target_calc = (
            int(base_tris * (tier.target_tris_pct / 100.0)) if base_tris > 0 else getattr(tier, "target_tris", 0)
        )
        target_str = f"  •  ~{target_calc:,} tris" if target_calc > 0 else f"  •  {tier.target_tris_pct:.0f}%"
        row_hdr.label(text=f"{tier_name}{target_str}{mat_suffix}", icon="MESH_DATA")

    state_labels = {"SOURCE": "Source", "BAKED": "Baked", "OUT_OF_SYNC": "Out of Sync"}
    row_hdr.label(text=state_labels.get(state, "Planned"))

    if idx > 0 and total_tiers > 1:
        op_del = row_hdr.operator("lod_tool.remove_lod_tier", text="", icon="X", emboss=False)
        op_del.tier_index = idx

    if idx > 0 and getattr(tier, "show_details", False):
        target_calc = (
            int(base_tris * (tier.target_tris_pct / 100.0)) if base_tris > 0 else getattr(tier, "target_tris", 0)
        )
        card.row().prop(
            tier, "target_tris_pct", text=f"Tris: {tier.target_tris_pct:.0f}%  (~{target_calc:,})", slider=True
        )
        dist_text = f"  ({tier.distance_m:.1f}m)" if tier.distance_m > 0 else ""
        card.row().prop(tier, "screen_size_pct", text=f"Screen: {tier.screen_size_pct:.0f}%{dist_text}", slider=True)

    return is_out_of_sync


def _draw_tab_lods(layout: Any, context: Any, props: Any) -> None:
    if len(getattr(props, "lods", [])) == 0 and hasattr(context, "scene") and hasattr(context.scene, "lod_tool"):
        if len(getattr(context.scene.lod_tool, "lods", [])) > 0:
            props = context.scene.lod_tool

    _draw_selection_banners(layout, context)

    box_lod = layout.box()
    box_lod.label(text="LOD Generation & Progression", icon="GEOMETRY_NODES")

    lod_preset_id = getattr(props, "lod_preset", "") or DEFAULT_LOD_PRESET_ID
    is_builtin_lod = not LODPresetManager.is_user_preset(lod_preset_id)

    row_preset = box_lod.row(align=True)
    row_preset.use_property_split = False
    row_preset.prop(props, "lod_preset", text="Preset")
    row_preset.popover(panel="OMNIMESH_PT_popover_lod_preset", icon="PREFERENCES", text="")
    op_dup_lod = row_preset.operator("lod_tool.duplicate_preset", text="", icon="DUPLICATE")
    if op_dup_lod is not None:
        op_dup_lod.preset_type = "LOD"
    sub_del_lod = row_preset.row(align=True)
    sub_del_lod.enabled = not is_builtin_lod
    sub_del_lod.operator("lod_tool.delete_lod_preset", text="", icon="X")

    box_lod.prop(props, "tau_sse", text="Visual Stability (τ_sse)", slider=True)

    active_obj = getattr(context, "active_object", None)
    base_tris = _calculate_base_tris(context, props, active_obj)
    base_mats = _calculate_base_materials(context, props, active_obj)

    has_out_of_sync = False
    if props.lods:
        for idx, tier in enumerate(props.lods):
            if _draw_lod_card(box_lod, tier, idx, base_tris, base_mats, len(props.lods)):
                has_out_of_sync = True

        row_add = box_lod.row(align=True)
        row_add.operator("lod_tool.add_lod_tier", text="Add LOD Tier", icon="ADD")

        row_cull = box_lod.row(align=True)
        row_cull.prop(props, "cull_screen_size_pct", text="Cull at Screen Size", slider=True)
    else:
        box_info = box_lod.box()
        box_info.label(text="No LOD tiers projected.", icon="INFO")
        box_info.operator("lod_tool.reset_to_preset", text="Project From Preset", icon="FILE_REFRESH")

    row_act = box_lod.row(align=True)
    row_act.use_property_split = False
    row_act.scale_y = 1.35
    action_text = "Update Out-of-Sync LODs" if has_out_of_sync else "Generate All LODs"
    op_gen = row_act.operator("lod_tool.generate_all", text=action_text, icon="GEOMETRY_NODES")
    if op_gen is not None:
        op_gen.only_out_of_sync = has_out_of_sync
    row_act.popover(panel="OMNIMESH_PT_popover_generate", icon="PREFERENCES", text="")

    # Interactive Simulation & Testing Section
    _draw_lods_testing_content(layout, context, props)


def _draw_lods_testing_content(layout: Any, context: Any, props: Any) -> None:
    box_test = layout.box()
    box_test.label(text="Interactive Simulation & Testing", icon="VIEW_CAMERA")

    row_test = box_test.row(align=True)
    row_test.use_property_split = False
    row_test.scale_y = 1.15
    if props.is_simulator_running:
        row_test.operator("lod_tool.toggle_simulator", text="Stop Simulator", icon="CANCEL")
    else:
        row_test.operator("lod_tool.toggle_simulator", text="Live Simulator", icon="PLAY")

    if getattr(props, "is_side_by_side_active", False):
        row_test.operator("lod_tool.toggle_side_by_side", text="Reset Alignment", icon="CANCEL")
    else:
        row_test.operator("lod_tool.toggle_side_by_side", text="Side-by-Side", icon="ALIGN_JUSTIFY")

    row_sweep = box_test.row(align=True)
    row_sweep.use_property_split = False
    row_sweep.prop(props, "virtual_distance_override", text="Distance (m)", slider=True)
    v_dist = getattr(props, "virtual_distance_override", 0.0)
    if isinstance(v_dist, (int, float)) and v_dist > 0.0:
        row_sweep.operator("lod_tool.reset_virtual_distance", text="", icon="LOOP_BACK")

    if getattr(props, "last_scrub_status", "") and (
        (isinstance(v_dist, (int, float)) and v_dist > 0.0) or getattr(props, "is_simulator_running", False)
    ):
        box_status = box_test.box()
        box_status.scale_y = 0.85
        row_status = box_status.row(align=True)
        row_status.alignment = "CENTER"
        row_status.label(text=props.last_scrub_status, icon="VIEW_CAMERA")


# Tab 5: Export


def _draw_tab_export(layout: Any, context: Any, props: Any) -> None:
    box_exp = layout.box()
    box_exp.label(text="Package Export", icon="EXPORT")

    exp_preset_id = getattr(props, "pbr_export_preset", "") or DEFAULT_PRESET_ID
    is_builtin_exp = PBRExportPresetManager.is_builtin(exp_preset_id)

    row_preset = box_exp.row(align=True)
    row_preset.use_property_split = False
    row_preset.prop(props, "pbr_export_preset", text="Preset")
    row_preset.popover(panel="OMNIMESH_PT_popover_export_preset", icon="PREFERENCES", text="")
    op_dup_exp = row_preset.operator("lod_tool.duplicate_preset", text="", icon="DUPLICATE")
    if op_dup_exp is not None:
        op_dup_exp.preset_type = "EXPORT"
    sub_del_exp = row_preset.row(align=True)
    sub_del_exp.enabled = not is_builtin_exp
    sub_del_exp.operator("lod_tool.delete_export_preset", text="", icon="X")

    row_path_exp = box_exp.row(align=True)
    row_path_exp.use_property_split = False
    row_path_exp.prop(props, "export_directory", text="Path")

    row2_exp = box_exp.row(align=True)
    row2_exp.use_property_split = False
    row2_exp.scale_y = 1.2
    row2_exp.operator("lod_tool.export_engine_package", text="Export", icon="PACKAGE")


# Central Panel


class OMNIMESH_PT_main(Panel):
    """OmniMesh Central Single-Panel with vertical icon tab navigation."""

    bl_label = "OmniMesh"
    bl_idname = "OMNIMESH_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OmniMesh"
    bl_order = 0

    def draw(self, context: Any) -> None:
        if not bpy or not context or not self.layout:
            return
        layout = self.layout
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = getattr(context.scene, "lod_tool", None)
        if not props:
            return

        # Top: Horizontal Segmented Workflow Navigation
        grid = layout.grid_flow(row_major=True, columns=4, even_columns=True, even_rows=True, align=True)
        grid.scale_y = 1.3
        grid.prop(props, "ui_active_tab", expand=True, icon_only=True)

        layout.separator(factor=0.3)
        active_tab = getattr(props, "ui_active_tab", "MODIFY")

        # Top: Target Scope Banner (Full Width, shown for Modify, LODs, Export)
        if active_tab != "IMPORT":
            box_scope = layout.box()
            row_scope_hdr = box_scope.row(align=True)
            row_scope_hdr.label(text="Target Scope", icon="FILTER")

            row_asset = box_scope.row(align=True)
            row_asset.use_property_split = False
            row_asset.scale_y = 1.15
            row_asset.prop(props, "active_asset", text="", icon="OUTLINER_COLLECTION")
            row_asset.operator("omnimesh.initialize_asset", text="", icon="ADD")

            # Dynamic Scope Feedback badge
            active_val = getattr(props, "active_asset", "ALL")
            if active_val == "ALL":
                avail = get_available_asset_names(context)
                if avail:
                    all_meshes = get_asset_base_meshes(context, "ALL")
                    box_scope.label(
                        text=f"↳ All Assets ({len(avail)} Collections, {len(all_meshes)} LOD0 Meshes)", icon="INFO"
                    )
                else:
                    box_scope.label(text="↳ No Root Assets in Scene", icon="INFO")
            elif active_val == "AUTO":
                eff_name = resolve_effective_asset_name(context, props)
                base_meshes = get_asset_base_meshes(context, eff_name) if eff_name else []
                box_scope.label(
                    text=f"↳ Active in Outliner: '{eff_name}' ({len(base_meshes)} Meshes)", icon="OUTLINER_COLLECTION"
                )
            else:
                base_meshes = get_asset_base_meshes(context, active_val) if active_val else []
                box_scope.label(text=f"↳ Target: '{active_val}' ({len(base_meshes)} LOD0 Meshes)", icon="CHECKMARK")

            layout.separator(factor=0.2)

        if active_tab == "IMPORT":
            _draw_tab_import(layout, context, props)
        elif active_tab in {"MODIFY", "ADD"}:
            _draw_tab_modify(layout, context, props)
        elif active_tab == "LODS":
            _draw_tab_lods(layout, context, props)
        elif active_tab == "EXPORT":
            _draw_tab_export(layout, context, props)


# Compatibility Wrappers


class OMNIMESH_PT_active_asset(Panel):
    """Compatibility wrapper for tests verifying active asset top header."""

    bl_label = "Asset"
    bl_idname = "OMNIMESH_PT_active_asset"

    def draw(self, context: Any) -> None:
        if not bpy or not context or not self.layout:
            return
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = getattr(context.scene, "lod_tool", None)
        if not props:
            return
        row = self.layout.row(align=True)
        row.prop(props, "active_asset", text="", icon="OUTLINER_COLLECTION")
        row.operator("omnimesh.initialize_asset", text="", icon="ADD")


class OMNIMESH_PT_import(Panel):
    """Compatibility drawer for Import tab."""

    bl_label = "1. Import"
    bl_idname = "OMNIMESH_PT_import"

    def draw(self, context: Any) -> None:
        if not bpy or not context or not self.layout:
            return
        props = getattr(context.scene, "lod_tool", None)
        if props:
            _draw_tab_import(self.layout, context, props)


class OMNIMESH_PT_add(Panel):
    """Compatibility drawer for Add tab."""

    bl_label = "2. Add"
    bl_idname = "OMNIMESH_PT_add"

    def draw(self, context: Any) -> None:
        if not bpy or not context or not self.layout:
            return
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = getattr(context.scene, "lod_tool", None)
        if props:
            _draw_tab_add(self.layout, context, props)


class OMNIMESH_PT_modify(Panel):
    """Compatibility drawer for Modify tab."""

    bl_label = "3. Modify"
    bl_idname = "OMNIMESH_PT_modify"

    def draw(self, context: Any) -> None:
        if not bpy or not context or not self.layout:
            return
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = getattr(context.scene, "lod_tool", None)
        if props:
            _draw_tab_modify(self.layout, context, props)


class OMNIMESH_PT_lods(Panel):
    """Compatibility drawer for LODs tab."""

    bl_label = "4. LODs"
    bl_idname = "OMNIMESH_PT_lods"

    def draw(self, context: Any) -> None:
        if not bpy or not context or not self.layout:
            return
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = getattr(context.scene, "lod_tool", None)
        if props:
            _draw_tab_lods(self.layout, context, props)


class OMNIMESH_PT_lods_testing(Panel):
    """Compatibility drawer for LODs testing section."""

    bl_label = "Testing & Inspection"
    bl_idname = "OMNIMESH_PT_lods_testing"

    def draw(self, context: Any) -> None:
        if not bpy or not context or not self.layout:
            return
        props = getattr(context.scene, "lod_tool", None)
        if props:
            _draw_lods_testing_content(self.layout, context, props)


class OMNIMESH_PT_export(Panel):
    """Compatibility drawer for Export tab."""

    bl_label = "5. Engine Export"
    bl_idname = "OMNIMESH_PT_export"

    def draw(self, context: Any) -> None:
        if not bpy or not context or not self.layout:
            return
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = getattr(context.scene, "lod_tool", None)
        if props:
            _draw_tab_export(self.layout, context, props)


# Registration lists: In the active N-Panel, ONLY the unified OMNIMESH_PT_main is registered!
PRIMARY_PANELS = (OMNIMESH_PT_main,)
SUBPANEL_CLASSES: tuple[Any, ...] = ()
PANEL_CLASSES = PRIMARY_PANELS + POPOVER_CLASSES


def register_panel() -> None:
    if not bpy:
        return
    reg_panels = {
        sub.__name__: sub
        for sub in getattr(bpy.types.Panel, "__subclasses__", list)()
        if getattr(sub, "is_registered", False)
    }
    for cls in PANEL_CLASSES:
        existing = reg_panels.get(cls.__name__) or getattr(bpy.types, cls.__name__, None)
        if existing is not None and getattr(existing, "is_registered", False):
            try:
                bpy.utils.unregister_class(existing)
            except Exception as exc:
                logger.debug("Safe unregister skipped %s: %s", cls.__name__, exc)
        if getattr(cls, "is_registered", False):
            try:
                bpy.utils.unregister_class(cls)
            except Exception as exc:
                logger.debug("Self unregister skipped %s: %s", cls.__name__, exc)
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            logger.warning("Could not register %s: %s", cls.__name__, exc)


def unregister_panel() -> None:
    if not bpy:
        return
    reg_panels = {
        sub.__name__: sub
        for sub in getattr(bpy.types.Panel, "__subclasses__", list)()
        if getattr(sub, "is_registered", False)
    }
    for cls in reversed(PANEL_CLASSES):
        existing = reg_panels.get(cls.__name__) or getattr(bpy.types, cls.__name__, None)
        if existing is not None and getattr(existing, "is_registered", False):
            try:
                bpy.utils.unregister_class(existing)
            except Exception as exc:
                logger.debug("Safe unregister skipped %s: %s", cls.__name__, exc)
        if getattr(cls, "is_registered", False):
            try:
                bpy.utils.unregister_class(cls)
            except Exception as exc:
                logger.debug("Self unregister skipped %s: %s", cls.__name__, exc)
