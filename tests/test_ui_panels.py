"""
Unit tests for OmniMesh 3-Panel UI architecture, UIList components, and operator helpers.
"""

from __future__ import annotations

import time
from typing import Any, cast
from unittest.mock import MagicMock

from ui.hud import LODViewportHUD, on_depsgraph_clear_toast
from ui.lists import register_lists, unregister_lists
from ui.operators import (
    LOD_OT_analyze_and_configure,
    LOD_OT_auto_match_pbr_folder,
    LOD_OT_clean_and_repair_materials,
    LOD_OT_clean_and_repair_mesh,
    LOD_OT_generate_all,
    LOD_OT_generate_collision_hulls,
    LOD_OT_import_pbr_set,
    LOD_OT_inspect_lod0,
    get_associated_armature,
    get_selected_mesh_objects,
    is_object_valid,
)
from ui.panel import (
    OMNIMESH_PT_main,
    OMNIMESH_PT_modify,
    PANEL_CLASSES,
    PRIMARY_PANELS,
    SUBPANEL_CLASSES,
    register_panel,
    unregister_panel,
)
from ui.popovers import OMNIMESH_PT_popover_collision, POPOVER_CLASSES
from ui.properties import register_properties, unregister_properties


def test_panel_class_hierarchy_and_order():
    """Verify panel architecture has unified root panel, popovers, bl_order, and registration order."""
    # Root Unified Panel
    assert OMNIMESH_PT_main.bl_idname == "OMNIMESH_PT_main"
    assert OMNIMESH_PT_main.bl_category == "OmniMesh"
    assert OMNIMESH_PT_main.bl_order == 0

    # Popovers (must use HEADER to prevent rogue N-panel/Misc sidebar tabs)
    assert len(POPOVER_CLASSES) == 10
    for popover_cls in POPOVER_CLASSES:
        assert getattr(popover_cls, "bl_space_type", None) == "VIEW_3D"
        assert getattr(popover_cls, "bl_region_type", None) == "HEADER"
        assert getattr(popover_cls, "bl_ui_units_x", None) in {16, 18, 20, 22}
        assert not hasattr(popover_cls, "bl_category")
        assert not hasattr(popover_cls, "bl_parent_id")

    # Registration tuple
    assert len(PRIMARY_PANELS) == 1
    assert len(SUBPANEL_CLASSES) == 0
    assert len(PANEL_CLASSES) == 11
    assert PANEL_CLASSES[0] is OMNIMESH_PT_main
    for idx, pop_cls in enumerate(POPOVER_CLASSES):
        assert PANEL_CLASSES[1 + idx] is pop_cls


def test_operator_helpers_mocked():
    """Test get_selected_mesh_objects, get_associated_armature, and is_object_valid."""
    assert is_object_valid(None) is False
    assert get_selected_mesh_objects(None) == []

    mock_armature = MagicMock()
    mock_armature.type = "ARMATURE"

    mock_mesh = MagicMock()
    mock_mesh.name = "SM_Prop"
    mock_mesh.type = "MESH"
    mock_mesh.parent = mock_armature
    mock_mesh.modifiers = []

    mock_context = MagicMock()
    mock_context.selected_objects = [mock_mesh]
    mock_context.active_object = mock_mesh

    assert get_selected_mesh_objects(mock_context) == [mock_mesh]
    assert get_associated_armature([mock_mesh]) == mock_armature

    # Modifier fallback
    mock_mesh2 = MagicMock()
    mock_mesh2.name = "SM_Skinned"
    mock_mesh2.type = "MESH"
    mock_mesh2.parent = None
    mock_mod = MagicMock()
    mock_mod.type = "ARMATURE"
    mock_mod.object = mock_armature
    mock_mesh2.modifiers = [mock_mod]

    assert get_associated_armature([mock_mesh2]) == mock_armature


def test_fix_lod0_operators_poll_and_exec_mocked():
    """Test poll and safe execution for LOD0 preflight and sanitization operators in headless mock."""
    mock_context = MagicMock()
    mock_mesh = MagicMock()
    mock_mesh.name = "SM_Test"
    mock_mesh.type = "MESH"
    mock_context.selected_objects = [mock_mesh]
    mock_context.active_object = mock_mesh
    mock_context.scene.lod_tool.lods = [MagicMock(), MagicMock()]
    mock_mesh.lod_tool.is_configured = False

    # Poll methods
    assert LOD_OT_inspect_lod0.poll(mock_context) is True
    assert LOD_OT_analyze_and_configure.poll(mock_context) is True
    assert LOD_OT_clean_and_repair_mesh.poll(mock_context) is True
    assert LOD_OT_generate_all.poll(mock_context) is True

    assert LOD_OT_inspect_lod0.poll(None) is False
    assert LOD_OT_analyze_and_configure.poll(None) is False
    assert LOD_OT_clean_and_repair_mesh.poll(None) is False
    assert LOD_OT_generate_collision_hulls.poll(mock_context) is True
    assert LOD_OT_generate_collision_hulls.poll(None) is False

    # Execute fallback when bpy is None
    op_inspect = LOD_OT_inspect_lod0()
    assert op_inspect.execute(None) == {"FINISHED"}

    op_analyze = LOD_OT_analyze_and_configure()
    assert op_analyze.execute(None) == {"FINISHED"}

    op_clean = LOD_OT_clean_and_repair_mesh()
    assert op_clean.execute(None) == {"FINISHED"}

    op_gen = LOD_OT_generate_all()
    assert op_gen.execute(None) == {"FINISHED"}

    op_mat = LOD_OT_clean_and_repair_materials()
    assert op_mat.execute(None) == {"FINISHED"}

    op_pbr = LOD_OT_import_pbr_set()
    assert op_pbr.execute(None) == {"FINISHED"}

    op_auto_pbr = LOD_OT_auto_match_pbr_folder()
    assert op_auto_pbr.execute(None) == {"FINISHED"}

    op_col_gen = LOD_OT_generate_collision_hulls()
    assert op_col_gen.execute(None) == {"FINISHED"}


def test_hud_cache_and_safety():
    """Verify LODViewportHUD cache updates and safe fallback in headless environment."""
    LODViewportHUD.update_cache(None)
    assert LODViewportHUD._cached_data == {}

    LODViewportHUD.update_simulation_hud(
        context=None,
        mode="LIVE",
        active_name="LOD1",
        screen_pct=50.0,
        distance_m=15.0,
        active_tris=1500,
        tracked_count=1,
    )
    assert LODViewportHUD._cached_data["is_simulating"] is True
    assert LODViewportHUD._cached_data["curr_tris"] == 1500

    LODViewportHUD.clear_simulation_hud()
    assert LODViewportHUD._cached_data["is_simulating"] is False

    # Safe call without crashing in headless mode
    LODViewportHUD.draw_callback_px()


def test_registration_lifecycle_safety():
    """Verify register/unregister functions run cleanly when bpy is None/mocked."""
    register_properties()
    unregister_properties()
    register_lists()
    unregister_lists()
    register_panel()
    unregister_panel()


def test_clean_and_repair_mesh_properties(monkeypatch):
    """Verify LOD_OT_clean_and_repair_mesh correctly accesses cleanup_* properties without AttributeError."""
    import ui.cleanup_ops as cleanup_ops

    mock_bpy, mock_bmesh = MagicMock(), MagicMock()
    monkeypatch.setattr(cleanup_ops, "bpy", mock_bpy)
    monkeypatch.setattr(cleanup_ops, "bmesh", mock_bmesh)

    op = cleanup_ops.LOD_OT_clean_and_repair_mesh()
    mock_context, mock_props = MagicMock(), MagicMock()
    mock_props.cleanup_enable_weld = False
    mock_props.cleanup_weld_distance = 0.0005
    mock_props.cleanup_enable_split_non_manifold = True
    mock_props.cleanup_enable_fill_holes = False
    mock_props.cleanup_hole_max_edges = 4
    mock_props.cleanup_enable_triangulate_ngons = False
    mock_props.cleanup_normal_policy = "OFF"
    mock_props.last_cleanup_summary = ""

    mock_mesh = MagicMock(type="MESH")
    mock_mesh.name = "TestMesh"
    mock_mesh.get.return_value = False
    mock_context.scene.lod_tool = mock_props
    mock_context.active_object = mock_mesh
    mock_context.selected_objects = [mock_mesh]

    res = op.execute(mock_context)
    assert res == {"FINISHED"}
    assert "Cleaned:" in mock_props.last_cleanup_summary


def test_clean_and_repair_mesh_with_apply_modifiers_opt_in(monkeypatch):
    """Verify clean_and_repair_mesh applies modifiers when cleanup_apply_modifiers is enabled."""
    import ui.cleanup_ops as cleanup_ops

    mock_bpy, mock_bmesh = MagicMock(), MagicMock()
    monkeypatch.setattr(cleanup_ops, "bpy", mock_bpy)
    monkeypatch.setattr(cleanup_ops, "bmesh", mock_bmesh)

    mock_mod_mgr = MagicMock()
    mock_mod_mgr.has_unapplied_modifiers.return_value = True
    mock_mod_mgr.apply_all_modifiers_in_place.return_value = True
    monkeypatch.setattr(cleanup_ops, "ModifierManager", mock_mod_mgr)

    op = cleanup_ops.LOD_OT_clean_and_repair_mesh()
    mock_context, mock_props = MagicMock(), MagicMock()
    mock_props.cleanup_apply_modifiers = True
    mock_props.cleanup_sync_viewport_settings = True
    mock_props.cleanup_enable_weld = False
    mock_props.cleanup_enable_split_non_manifold = False
    mock_props.cleanup_enable_fill_holes = False
    mock_props.cleanup_enable_triangulate_ngons = False
    mock_props.cleanup_normal_policy = "OFF"
    mock_props.last_cleanup_summary = ""

    mock_mesh = MagicMock(type="MESH")
    mock_mesh.name = "TestMesh"
    mock_mesh.get.return_value = False
    mock_context.scene.lod_tool = mock_props
    mock_context.active_object = mock_mesh
    mock_context.selected_objects = [mock_mesh]

    res = op.execute(mock_context)
    assert res == {"FINISHED"}
    mock_mod_mgr.sync_viewport_to_render_settings.assert_called_once_with(mock_mesh)
    mock_mod_mgr.apply_all_modifiers_in_place.assert_called_once_with(mock_mesh, preserve_armature=True)
    assert "modifier(s) baked" in mock_props.last_cleanup_summary


def test_operator_classes_no_duplicates():
    """Ensure OPERATOR_CLASSES contains unique bl_idnames and no registration collisions."""
    from ui.operators import OPERATOR_CLASSES

    idnames = [getattr(cls, "bl_idname", None) for cls in OPERATOR_CLASSES if hasattr(cls, "bl_idname")]
    assert len(idnames) == len(set(idnames)), f"Duplicate bl_idnames found: {idnames}"
    assert "lod_tool.clean_and_repair_mesh" in idnames
    assert "lod_tool.inspect_lod0" in idnames
    assert "lod_tool.generate_all" in idnames
    assert "lod_tool.generate_collision_hulls" in idnames
    assert "lod_tool.import_pbr_set" in idnames
    assert "lod_tool.apply_all_modifiers" in idnames
    assert "lod_tool.apply_transforms" in idnames


def test_lod_ot_apply_transforms(monkeypatch):
    """Test LOD_OT_apply_transforms operator execution."""
    import ui.cleanup_ops as cleanup_ops

    mock_bpy = MagicMock()
    monkeypatch.setattr(cleanup_ops, "bpy", mock_bpy)

    op = cleanup_ops.LOD_OT_apply_transforms()
    mock_context = MagicMock()
    mock_mesh = MagicMock()
    mock_mesh.name = "TestMesh"
    mock_mesh.type = "MESH"
    mock_mesh.get.return_value = False
    mock_context.selected_objects = [mock_mesh]
    mock_context.active_object = mock_mesh

    res = op.execute(mock_context)
    assert res == {"FINISHED"}


def test_lod_ot_apply_all_modifiers(monkeypatch):
    """Test LOD_OT_apply_all_modifiers operator execution."""
    import ui.cleanup_ops as cleanup_ops

    mock_bpy = MagicMock()
    monkeypatch.setattr(cleanup_ops, "bpy", mock_bpy)

    mock_mod_mgr = MagicMock()
    mock_mod_mgr.apply_all_modifiers_in_place.return_value = True
    monkeypatch.setattr(cleanup_ops, "ModifierManager", mock_mod_mgr)

    op = cleanup_ops.LOD_OT_apply_all_modifiers()
    mock_context = MagicMock()
    mock_mesh = MagicMock()
    mock_mesh.name = "TestMesh"
    mock_mesh.type = "MESH"
    mock_mesh.get.return_value = False
    mock_context.selected_objects = [mock_mesh]
    mock_context.active_object = mock_mesh

    res = op.execute(mock_context)
    assert res == {"FINISHED"}
    mock_mod_mgr.apply_all_modifiers_in_place.assert_called_once_with(mock_mesh, preserve_armature=True)


def test_preset_delete_button_disabled_for_factory_presets():
    """Verify that delete button is disabled (enabled=False) for factory presets and enabled for custom."""
    from core.pbr_presets import PBRExportPresetManager, PBRImportPresetManager

    # 1. Built-in factory presets must report is_builtin=True
    assert PBRImportPresetManager.is_builtin("unreal_engine_5") is True
    assert PBRImportPresetManager.is_builtin("standard_pbr_split") is True
    assert PBRExportPresetManager.is_builtin("unreal_engine_5") is True
    assert PBRExportPresetManager.is_builtin("unity_hdrp") is True

    # 2. Empty or invalid preset ID must safely fall back to is_builtin=True (locked)
    assert PBRImportPresetManager.is_builtin("") is True
    assert PBRImportPresetManager.is_builtin("non_existent_preset_xyz") is True
    assert PBRExportPresetManager.is_builtin("") is True
    assert PBRExportPresetManager.is_builtin("non_existent_preset_xyz") is True

    # 3. Simulate Panel 1 (Import) draw sub_del.enabled
    mock_context = MagicMock()
    mock_props = MagicMock()
    mock_context.scene.lod_tool = mock_props

    mock_props.pbr_import_preset = "unreal_engine_5"
    raw_preset = getattr(mock_props, "pbr_import_preset", "")
    preset_id = str(raw_preset).strip() or "unreal_engine_5"
    is_builtin = PBRImportPresetManager.is_builtin(preset_id)
    enabled_for_factory = not is_builtin
    assert enabled_for_factory is False, "X-Button must be disabled (enabled=False) for factory presets"

    # Custom preset
    PBRImportPresetManager.load_presets()["my_custom_import"] = {"_is_builtin": False, "name": "My Custom"}
    is_custom_builtin = PBRImportPresetManager.is_builtin("my_custom_import")
    assert is_custom_builtin is False

    # 4. Engine Import Presets
    from core.engine_import_presets import EngineImportPresetManager

    assert EngineImportPresetManager.is_builtin("msfs_2024_aircraft") is True
    assert EngineImportPresetManager.is_builtin("") is True

    # 5. Config Presets
    from core.config_presets import ConfigPresetManager

    assert ConfigPresetManager.is_builtin("plane_general_aviation") is True
    assert ConfigPresetManager.is_builtin("") is True

    # 6. LOD Presets
    from core.lod_presets import LODPresetManager

    assert LODPresetManager.is_user_preset("balanced_gameplay") is False
    assert (not LODPresetManager.is_user_preset("balanced_gameplay")) is True

    # 7. Simulate Panel 4 (Export) draw sub_del_exp.enabled
    mock_props.pbr_export_preset = "unreal_engine_5"
    raw_exp = str(getattr(mock_props, "pbr_export_preset", "")).strip() or "unreal_engine_5"
    export_preset_id = raw_exp or "unreal_engine_5"
    is_builtin_exp = PBRExportPresetManager.is_builtin(export_preset_id)
    enabled_exp_factory = not is_builtin_exp
    assert enabled_exp_factory is False, "Export X-Button must be disabled for factory presets"


def test_modify_panel_collision_row_and_popover(monkeypatch):
    """Verify OMNIMESH_PT_modify and OMNIMESH_PT_popover_collision draw without exceptions."""
    import ui.panel as panel_mod
    import ui.popovers as popovers_mod

    mock_bpy = MagicMock()
    monkeypatch.setattr(panel_mod, "bpy", mock_bpy)
    monkeypatch.setattr(popovers_mod, "bpy", mock_bpy)

    panel_modify = OMNIMESH_PT_modify()
    popover_col = OMNIMESH_PT_popover_collision()

    mock_context = MagicMock()
    mock_props = MagicMock()
    mock_mesh = MagicMock()
    mock_mesh.name = "SM_Rock"
    mock_mesh.type = "MESH"
    mock_mesh.get.return_value = False

    mock_context.scene.lod_tool = mock_props
    mock_context.active_object = mock_mesh
    mock_context.selected_objects = [mock_mesh]

    mock_props.export_base_name = ""
    mock_props.last_material_cleanup_summary = ""
    mock_props.last_generated_collider_count = 3
    mock_props.collision_decomposition_mode = "PER_OBJECT"
    mock_props.collision_hull_count = 4
    mock_props.collision_concavity_threshold = 0.05
    mock_props.collision_max_verts_per_hull = 32

    # Draw OMNIMESH_PT_modify
    mock_layout = MagicMock()
    cast(Any, panel_modify).layout = mock_layout
    panel_modify.draw(mock_context)
    assert mock_layout.box.called

    # Draw OMNIMESH_PT_popover_collision
    cast(Any, popover_col).layout = mock_layout
    popover_col.draw(mock_context)
    assert mock_layout.prop.called


def test_popover_sanitize_and_modify_panel_layout(monkeypatch):
    """Verify OMNIMESH_PT_modify and OMNIMESH_PT_popover_sanitize draw correctly with preflight diagnostics."""
    import ui.panel as panel_mod
    import ui.popovers as popovers_mod
    from ui.panel import OMNIMESH_PT_modify
    from ui.popovers import OMNIMESH_PT_popover_sanitize

    mock_bpy = MagicMock()
    monkeypatch.setattr(panel_mod, "bpy", mock_bpy)
    monkeypatch.setattr(popovers_mod, "bpy", mock_bpy)

    panel_modify, popover_san = OMNIMESH_PT_modify(), OMNIMESH_PT_popover_sanitize()
    mock_context, mock_props = MagicMock(), MagicMock()
    mock_mesh = MagicMock(type="MESH", name="SM_Chair")
    mock_mesh.get.return_value = False

    mock_context.scene.lod_tool = mock_props
    mock_context.active_object = mock_mesh
    mock_context.selected_objects = [mock_mesh]
    mock_props.export_base_name = ""
    mock_props.last_cleanup_summary = "Cleaned: 2 loose verts."
    mock_props.last_material_cleanup_summary = "Cleaned: 1 slot purged."
    mock_props.last_generated_collider_count = 0

    mock_layout = MagicMock()
    cast(Any, panel_modify).layout = mock_layout
    panel_modify.draw(mock_context)
    assert mock_layout.box.called

    mock_props.preflight_inspected = True
    mock_props.preflight_is_clean = False
    mock_props.preflight_summary_text = "⚠ Issues: 2 Loose Verts"
    mock_props.preflight_unapplied_scale = True
    mock_props.preflight_loose_verts = 2
    mock_props.preflight_loose_edges = 0
    mock_props.preflight_non_manifold_edges = 1
    mock_props.preflight_degenerate_tris = 0
    mock_props.cleanup_enable_weld = True
    mock_props.cleanup_enable_fill_holes = True

    mock_san_layout = MagicMock()
    cast(Any, popover_san).layout = mock_san_layout
    popover_san.draw(mock_context)
    assert mock_san_layout.label.called
    assert mock_san_layout.prop.called

    mock_props.preflight_is_clean = True
    mock_props.preflight_unapplied_scale = False
    mock_props.preflight_loose_verts = 0
    mock_props.preflight_non_manifold_edges = 0
    popover_san.draw(mock_context)


def test_viewport_hud_toast_lifecycle():
    """Verify LODViewportHUD toast notification show, clear, and draw lifecycle."""
    LODViewportHUD.show_toast("Cleaned: 1 transform(s) applied.")
    assert LODViewportHUD._toast_message == "Cleaned: 1 transform(s) applied."
    assert LODViewportHUD._toast_time > 0
    LODViewportHUD.draw_callback_px()

    on_depsgraph_clear_toast(None, None)
    LODViewportHUD._toast_time = time.time() - 4.0
    on_depsgraph_clear_toast(None, None)
    assert LODViewportHUD._toast_message == ""

    LODViewportHUD.show_toast("Another message")
    assert LODViewportHUD._toast_message == "Another message"
    LODViewportHUD.clear_toast()
    assert LODViewportHUD._toast_message == ""


def test_add_panel_draw(monkeypatch):
    """Verify OMNIMESH_PT_add draws the Vehicle & Asset Configurator, presets, and action buttons."""
    import ui.panel as panel_mod
    from ui.panel import OMNIMESH_PT_add

    mock_bpy = MagicMock()
    monkeypatch.setattr(panel_mod, "bpy", mock_bpy)

    panel_add = OMNIMESH_PT_add()

    # 1. Null / early exit guards
    cast(Any, panel_add).layout = None
    panel_add.draw(None)

    mock_layout = MagicMock()
    cast(Any, panel_add).layout = mock_layout

    # 2. Context with no config_presets and no interaction
    mock_context = MagicMock()
    mock_props = MagicMock()
    mock_props.config_presets = None
    mock_props.interaction = None
    mock_props.last_generated_collider_count = 0
    mock_context.scene.lod_tool = mock_props
    panel_add.draw(mock_context)
    assert mock_layout.box.called

    # 3. Built-in preset + Impostor + Colliders + Interaction Trigger
    mock_layout.reset_mock()
    mock_box_gen = MagicMock()
    mock_box_cfg = MagicMock()
    mock_box_int = MagicMock()
    mock_row_p = MagicMock()
    mock_sub_del = MagicMock()
    mock_row_act = MagicMock()
    mock_row_hlp = MagicMock()
    mock_layout.box.side_effect = [mock_box_gen, mock_box_cfg, mock_box_int]
    mock_box_cfg.row.side_effect = [mock_row_p, mock_row_act, mock_row_hlp]
    mock_row_p.row.return_value = mock_sub_del

    mock_cfg_props = MagicMock()
    mock_cfg_props.config_preset = "plane_general_aviation"
    mock_cfg_props.last_spawn_summary = "Added 4 marker(s)"
    mock_cfg_props.show_helpers = False
    mock_props.config_presets = mock_cfg_props

    mock_int_props = MagicMock()
    mock_int_props.role = "BUTTON"
    mock_int_props.shape = "BOX"
    mock_props.interaction = mock_int_props

    panel_add.draw(mock_context)

    mock_box_gen.label.assert_any_call(text="Generate", icon="MODIFIER")
    mock_box_cfg.label.assert_any_call(text="Vehicle & Asset Configurator", icon="PRESET")
    mock_row_p.prop.assert_called_with(mock_cfg_props, "config_preset", text="Preset")
    mock_row_p.operator.assert_called_with("omnimesh.duplicate_config_preset", text="", icon="DUPLICATE")
    assert mock_sub_del.enabled is False
    mock_sub_del.operator.assert_called_with("omnimesh.delete_config_preset", text="", icon="X")
    mock_row_p.popover.assert_called_with(panel="OMNIMESH_PT_popover_config_preset", icon="PREFERENCES", text="")
    mock_row_act.operator.assert_called_with("omnimesh.add_config_preset", text="Add Features", icon="ADD")
    mock_box_cfg.label.assert_any_call(text="Added 4 marker(s)", icon="CHECKMARK")
    mock_box_int.label.assert_any_call(text="Interaction Trigger / Clickspots", icon="GIZMO")

    # 4. Custom preset (delete enabled)
    from core.config_presets import ConfigPresetManager

    ConfigPresetManager.load_presets()["my_custom_vehicle"] = {"_is_builtin": False, "name": "My Custom"}
    mock_layout.box.side_effect = [mock_box_gen, mock_box_cfg, mock_box_int]
    mock_box_cfg.reset_mock()
    mock_box_cfg.row.side_effect = [mock_row_p, mock_row_act, mock_row_hlp]
    mock_cfg_props.config_preset = "my_custom_vehicle"
    mock_cfg_props.last_spawn_summary = ""
    mock_cfg_props.show_helpers = True
    panel_add.draw(mock_context)
    assert mock_sub_del.enabled is True
    assert mock_box_cfg.box.called


def test_cull_interior_faces_and_multi_mesh_modify_ops(monkeypatch):
    """Verify LOD_OT_cull_interior_faces and LOD_OT_voxel_scan_cleanup operate on all LOD0 meshes (plus negative cases)."""
    import ui.chunk_ops as chunk_ops
    import ui.cleanup_ops as cleanup_ops

    mock_bpy, mock_bmesh = MagicMock(), MagicMock()
    monkeypatch.setattr(cleanup_ops, "bpy", mock_bpy)
    monkeypatch.setattr(cleanup_ops, "bmesh", mock_bmesh)
    monkeypatch.setattr(chunk_ops, "bpy", mock_bpy)

    # 1. Negative test: no LOD0 or selected meshes -> CANCELLED
    monkeypatch.setattr(cleanup_ops, "get_lod0_mesh_objects", lambda ctx: [])
    monkeypatch.setattr(cleanup_ops, "get_selected_mesh_objects", lambda ctx: [])
    op_cull = cleanup_ops.LOD_OT_cull_interior_faces()
    assert cleanup_ops.LOD_OT_cull_interior_faces.poll(None) is False
    mock_ctx = MagicMock()
    assert op_cull.execute(mock_ctx) == {"CANCELLED"}

    # 2. Multi-mesh LOD0 interior polygon culling
    m1, m2 = MagicMock(type="MESH", name="PartA_LOD0"), MagicMock(type="MESH", name="PartB_LOD0")
    monkeypatch.setattr(cleanup_ops, "get_lod0_mesh_objects", lambda ctx: [m1, m2])
    mock_occ = MagicMock()
    mock_occ.cull_interior_faces.return_value = {"culled_faces": 5, "culled_islands": 1}
    monkeypatch.setattr(cleanup_ops, "HardenedOcclusionCuller", mock_occ)

    mock_props = MagicMock()
    mock_props.occlusion_ray_density = 16
    mock_props.occlusion_evaluate_alpha = True
    mock_ctx.scene.lod_tool = mock_props

    assert cleanup_ops.LOD_OT_cull_interior_faces.poll(mock_ctx) is True
    assert op_cull.execute(mock_ctx) == {"FINISHED"}
    assert mock_occ.cull_interior_faces.call_count == 2
    assert mock_props.last_culled_faces_count == 10
    assert mock_props.last_culled_islands_count == 2

    # 3. Multi-mesh LOD0 Voxel Reconstruction (plus negative empty check)
    monkeypatch.setattr(chunk_ops, "get_lod0_mesh_objects", lambda ctx: [])
    monkeypatch.setattr(chunk_ops, "get_selected_mesh_objects", lambda ctx: [])
    mock_ctx.active_object = None
    op_vox = chunk_ops.LOD_OT_voxel_scan_cleanup()
    assert chunk_ops.LOD_OT_voxel_scan_cleanup.poll(mock_ctx) is False
    assert op_vox.execute(mock_ctx) == {"CANCELLED"}

    monkeypatch.setattr(chunk_ops, "get_lod0_mesh_objects", lambda ctx: [m1, m2])
    mock_props.scan_remesh_voxel_size = 0.05
    assert chunk_ops.LOD_OT_voxel_scan_cleanup.poll(mock_ctx) is True
    assert op_vox.execute(mock_ctx) == {"FINISHED"}
    assert mock_bpy.ops.object.voxel_remesh.call_count == 2


def test_main_panel_tab_switching_and_target_asset_visibility(monkeypatch):
    """Verify OMNIMESH_PT_main draws horizontal tab bar and scopes Target Asset across tabs."""
    import ui.panel as panel_mod

    mock_bpy = MagicMock()
    monkeypatch.setattr(panel_mod, "bpy", mock_bpy)

    main_panel = OMNIMESH_PT_main()
    mock_layout = MagicMock()
    mock_grid = MagicMock()
    mock_row_asset = MagicMock()
    mock_box_scope = MagicMock()
    mock_layout.grid_flow.return_value = mock_grid
    mock_layout.row.return_value = mock_row_asset
    mock_layout.box.return_value = mock_box_scope
    mock_box_scope.row.return_value = mock_row_asset
    cast(Any, main_panel).layout = mock_layout

    mock_ctx = MagicMock()
    mock_props = MagicMock()
    mock_props.active_asset = "Fuselage"
    mock_props.export_base_name = "Fuselage"
    mock_ctx.scene.lod_tool = mock_props
    monkeypatch.setattr(panel_mod, "resolve_lod_context", lambda ctx: (mock_props, None, False))

    # 1. Null guards
    cast(Any, main_panel).layout = None
    main_panel.draw(None)
    cast(Any, main_panel).layout = mock_layout

    # 2. Iterate through all 4 workflow tabs
    for tab_id in ("IMPORT", "MODIFY", "LODS", "EXPORT"):
        mock_props.ui_active_tab = tab_id
        mock_grid.reset_mock()
        mock_row_asset.reset_mock()
        main_panel.draw(mock_ctx)

        # Tab navigation prop always requested on grid_flow
        mock_grid.prop.assert_called_with(mock_props, "ui_active_tab", expand=True, icon_only=False)

        # Target Asset selector presence depends on tab
        has_target_asset = any(
            len(c.args) > 1 and c.args[1] == "active_asset" for c in mock_row_asset.prop.call_args_list
        )
        if tab_id == "IMPORT":
            assert not has_target_asset
        else:
            assert has_target_asset


def test_lods_ui_reordering_materials_and_side_by_side(monkeypatch):
    """Verify LOD card material counter, removal of solo eye icon, button ordering, and side-by-side operator."""
    import ui.panel as panel_mod

    mock_bpy = MagicMock()
    monkeypatch.setattr(panel_mod, "bpy", mock_bpy)

    mock_box = MagicMock()
    mock_card = MagicMock()
    mock_row = MagicMock()
    mock_box.box.return_value = mock_card
    mock_card.row.return_value = mock_row

    tier0 = MagicMock(name="LOD0", actual_tris=1000, mat_slots_count=3, is_impostor=False, show_details=False)
    panel_mod._draw_lod_card(mock_box, tier0, 0, 1000, 3, 2)
    assert not any(c.args and "lod_tool.solo_tier" in str(c.args[0]) for c in mock_row.operator.call_args_list)
    assert any(c.kwargs.get("text", "").endswith("3 mats") for c in mock_row.label.call_args_list)

    mock_props = MagicMock(
        lods=[tier0],
        cull_screen_size_pct=5.0,
        is_simulator_running=False,
        is_side_by_side_active=False,
    )
    mock_ctx = MagicMock(active_object=None, scene=MagicMock(lod_tool=mock_props))
    monkeypatch.setattr(panel_mod, "resolve_effective_asset_name", lambda ctx, props: "Asset")
    monkeypatch.setattr(panel_mod, "get_asset_base_meshes", lambda ctx, name: [])

    mock_layout = MagicMock()
    mock_test_box = MagicMock()
    mock_test_row = MagicMock()
    mock_layout.box.return_value = mock_test_box
    mock_test_box.row.return_value = mock_test_row

    mock_props.is_side_by_side_active = False
    panel_mod._draw_lods_testing_content(mock_layout, mock_ctx, mock_props)
    assert any(
        "lod_tool.toggle_side_by_side" in str(c) and c.kwargs.get("text") == "Side-by-Side"
        for c in mock_test_row.operator.call_args_list
    )

    mock_test_row.reset_mock()
    mock_props.is_side_by_side_active = True
    panel_mod._draw_lods_testing_content(mock_layout, mock_ctx, mock_props)
    assert any(
        "lod_tool.toggle_side_by_side" in str(c) and c.kwargs.get("text") == "Reset Alignment"
        for c in mock_test_row.operator.call_args_list
    )
