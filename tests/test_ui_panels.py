"""
Unit tests for OmniMesh 3-Panel UI architecture, UIList components, and operator helpers.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from ui.hud import LODViewportHUD
from ui.lists import LOD_UL_tier_list, register_lists, unregister_lists
from ui.operators import (
    LOD_OT_analyze_and_configure,
    LOD_OT_auto_match_pbr_folder,
    LOD_OT_clean_and_repair_materials,
    LOD_OT_clean_and_repair_mesh,
    LOD_OT_generate_all,
    LOD_OT_generate_collision_hulls,
    LOD_OT_import_pbr_set,
    LOD_OT_inspect_lod0,
    LOD_OT_remove_collision_hulls,
    get_associated_armature,
    get_selected_mesh_objects,
    is_object_valid,
)
from ui.panel import (
    PANEL_CLASSES,
    PRIMARY_PANELS,
    SUBPANEL_CLASSES,
    OMNIMESH_PT_export,
    OMNIMESH_PT_import,
    OMNIMESH_PT_lods,
    OMNIMESH_PT_modify,
    register_panel,
    unregister_panel,
)
from ui.popovers import OMNIMESH_PT_popover_collision, POPOVER_CLASSES
from ui.properties import register_properties, unregister_properties


def test_panel_class_hierarchy_and_order():
    """Verify panel architecture has correct root panels, subpanels, popovers, bl_order, and registration order."""
    # Root Panels
    assert OMNIMESH_PT_import.bl_idname == "OMNIMESH_PT_import"
    assert OMNIMESH_PT_import.bl_category == "OmniMesh"
    assert OMNIMESH_PT_import.bl_order == 0

    assert OMNIMESH_PT_modify.bl_idname == "OMNIMESH_PT_modify"
    assert OMNIMESH_PT_modify.bl_category == "OmniMesh"
    assert OMNIMESH_PT_modify.bl_order == 1

    assert OMNIMESH_PT_lods.bl_idname == "OMNIMESH_PT_lods"
    assert OMNIMESH_PT_lods.bl_category == "OmniMesh"
    assert OMNIMESH_PT_lods.bl_order == 2

    assert OMNIMESH_PT_export.bl_idname == "OMNIMESH_PT_export"
    assert OMNIMESH_PT_export.bl_category == "OmniMesh"
    assert OMNIMESH_PT_export.bl_order == 3

    # Subpanels (testing subpanel under Panel 3, MSFS spatial subpanel under Panel 4)
    assert len(SUBPANEL_CLASSES) == 2
    assert SUBPANEL_CLASSES[0].bl_idname == "OMNIMESH_PT_lods_testing"
    assert SUBPANEL_CLASSES[1].bl_idname == "OMNIMESH_PT_export_msfs_spatial"

    # Popovers (must use HEADER to prevent rogue N-panel/Misc sidebar tabs)
    assert len(POPOVER_CLASSES) == 11
    for popover_cls in POPOVER_CLASSES:
        assert getattr(popover_cls, "bl_space_type", None) == "VIEW_3D"
        assert getattr(popover_cls, "bl_region_type", None) == "HEADER"
        assert getattr(popover_cls, "bl_ui_units_x", None) in {16, 18, 20, 22}
        # Popovers must NOT have bl_category or bl_parent_id
        assert not hasattr(popover_cls, "bl_category")
        assert not hasattr(popover_cls, "bl_parent_id")

    # Registration tuple (parent-first topological order)
    assert len(PRIMARY_PANELS) == 4
    assert len(SUBPANEL_CLASSES) == 2
    assert len(PANEL_CLASSES) == 17
    assert PANEL_CLASSES[0] is OMNIMESH_PT_import
    assert PANEL_CLASSES[1] is OMNIMESH_PT_modify
    assert PANEL_CLASSES[2] is OMNIMESH_PT_lods
    assert PANEL_CLASSES[3] is OMNIMESH_PT_export
    assert PANEL_CLASSES[4] is SUBPANEL_CLASSES[0]
    assert PANEL_CLASSES[5] is SUBPANEL_CLASSES[1]
    for idx, pop_cls in enumerate(POPOVER_CLASSES):
        assert PANEL_CLASSES[6 + idx] is pop_cls


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

    op_col_rem = LOD_OT_remove_collision_hulls()
    assert op_col_rem.execute(None) == {"FINISHED"}


def test_ui_list_draw_item_mock():
    """Verify LOD_UL_tier_list draw_item does not raise exceptions."""
    ui_list = LOD_UL_tier_list()
    mock_layout = MagicMock()
    mock_row = MagicMock()
    mock_layout.row.return_value = mock_row
    mock_split1 = MagicMock()
    mock_row.split.return_value = mock_split1
    mock_split2 = MagicMock()
    mock_split1.split.return_value = mock_split2

    mock_item = MagicMock()
    mock_item.lod_index = 0
    mock_item.screen_size_pct = 100.0
    mock_item.actual_tris = 5000
    mock_item.target_tris = 5000
    mock_item.distance_m = 15.0

    ui_list.layout_type = "DEFAULT"
    ui_list.draw_item(
        context=None,
        layout=mock_layout,
        data=None,
        item=mock_item,
        icon=None,
        active_data=None,
        active_propname=None,
    )
    assert mock_layout.row.called


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

    mock_bpy = MagicMock()
    mock_bmesh = MagicMock()
    monkeypatch.setattr(cleanup_ops, "bpy", mock_bpy)
    monkeypatch.setattr(cleanup_ops, "bmesh", mock_bmesh)

    op = cleanup_ops.LOD_OT_clean_and_repair_mesh()
    mock_context = MagicMock()
    mock_props = MagicMock()
    # Configure exact LODToolSettings property names
    mock_props.cleanup_enable_weld = False
    mock_props.cleanup_weld_distance = 0.0005
    mock_props.cleanup_enable_split_non_manifold = True
    mock_props.cleanup_enable_fill_holes = False
    mock_props.cleanup_hole_max_edges = 4
    mock_props.cleanup_enable_triangulate_ngons = False
    mock_props.cleanup_normal_policy = "OFF"
    mock_props.last_cleanup_summary = ""

    mock_mesh = MagicMock()
    mock_mesh.name = "TestMesh"
    mock_mesh.type = "MESH"
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

    mock_bpy = MagicMock()
    mock_bmesh = MagicMock()
    monkeypatch.setattr(cleanup_ops, "bpy", mock_bpy)
    monkeypatch.setattr(cleanup_ops, "bmesh", mock_bmesh)

    mock_mod_mgr = MagicMock()
    mock_mod_mgr.has_unapplied_modifiers.return_value = True
    mock_mod_mgr.apply_all_modifiers_in_place.return_value = True
    monkeypatch.setattr(cleanup_ops, "ModifierManager", mock_mod_mgr)

    op = cleanup_ops.LOD_OT_clean_and_repair_mesh()
    mock_context = MagicMock()
    mock_props = MagicMock()
    mock_props.cleanup_apply_modifiers = True
    mock_props.cleanup_sync_viewport_settings = True
    mock_props.cleanup_enable_weld = False
    mock_props.cleanup_enable_split_non_manifold = False
    mock_props.cleanup_enable_fill_holes = False
    mock_props.cleanup_enable_triangulate_ngons = False
    mock_props.cleanup_normal_policy = "OFF"
    mock_props.last_cleanup_summary = ""

    mock_mesh = MagicMock()
    mock_mesh.name = "TestMesh"
    mock_mesh.type = "MESH"
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
    assert PBRExportPresetManager.is_builtin("godot_4_orm") is True

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

    # 4. Simulate Panel 4 (Export) draw sub_del_exp.enabled
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
    panel_modify.layout = mock_layout
    panel_modify.draw(mock_context)
    assert mock_layout.row.called

    # Draw OMNIMESH_PT_popover_collision
    popover_col.layout = mock_layout
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

    panel_modify = OMNIMESH_PT_modify()
    popover_san = OMNIMESH_PT_popover_sanitize()

    mock_context = MagicMock()
    mock_props = MagicMock()
    mock_mesh = MagicMock()
    mock_mesh.name = "SM_Chair"
    mock_mesh.type = "MESH"
    mock_mesh.get.return_value = False

    mock_context.scene.lod_tool = mock_props
    mock_context.active_object = mock_mesh
    mock_context.selected_objects = [mock_mesh]

    mock_props.export_base_name = ""
    mock_props.last_cleanup_summary = "Cleaned: 2 loose verts."
    mock_props.last_material_cleanup_summary = "Cleaned: 1 slot purged."
    mock_props.last_generated_collider_count = 0

    # 1. Verify Modify Panel draw with 3 clean rows
    mock_layout = MagicMock()
    panel_modify.layout = mock_layout
    panel_modify.draw(mock_context)
    assert mock_layout.row.called

    # 2. Verify Popover Sanitize draw when preflight inspected with issues
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
    popover_san.layout = mock_san_layout
    popover_san.draw(mock_context)
    assert mock_san_layout.label.called
    assert mock_san_layout.prop.called

    # 3. Verify Popover Sanitize draw when preflight is clean
    mock_props.preflight_is_clean = True
    mock_props.preflight_unapplied_scale = False
    mock_props.preflight_loose_verts = 0
    mock_props.preflight_non_manifold_edges = 0
    popover_san.draw(mock_context)


def test_viewport_hud_toast_lifecycle():
    """Verify LODViewportHUD toast notification show, clear, and draw lifecycle."""
    from ui.hud import LODViewportHUD, on_depsgraph_clear_toast
    import time

    # 1. Show toast
    LODViewportHUD.show_toast("Cleaned: 1 transform(s) applied.")
    assert LODViewportHUD._toast_message == "Cleaned: 1 transform(s) applied."
    assert LODViewportHUD._toast_time > 0

    # 2. Draw callback with toast
    LODViewportHUD.draw_callback_px()

    # 3. Depsgraph update grace period check
    on_depsgraph_clear_toast(None, None)
    # Right away (< duration), toast shouldn't be dismissed immediately
    # Simulate elapsed time > duration (3.5s)
    LODViewportHUD._toast_time = time.time() - 4.0
    on_depsgraph_clear_toast(None, None)
    assert LODViewportHUD._toast_message == ""

    # 4. Explicit clear toast
    LODViewportHUD.show_toast("Another message")
    assert LODViewportHUD._toast_message == "Another message"
    LODViewportHUD.clear_toast()
    assert LODViewportHUD._toast_message == ""


def test_collection_first_tier_projection_and_reset():
    """Verify collection-first tier projection, state badges, and reset operator."""
    from ui.lod_ops import LOD_OT_reset_to_preset

    mock_context = MagicMock()
    mock_props = MagicMock()
    mock_context.scene.lod_tool = mock_props

    # Mock tier items
    created_tiers = []

    def mock_add():
        tier = MagicMock()
        tier.name = f"LOD{len(created_tiers)}"
        tier.target_tris_pct = 100.0 if not created_tiers else 50.0
        tier.screen_size_pct = 100.0 if not created_tiers else 50.0
        tier.actual_tris = 0
        tier.state = "PLANNED"
        tier.last_baked_target_pct = -1.0
        created_tiers.append(tier)
        return tier

    mock_props.lods.add = mock_add
    mock_props.lods.clear = lambda: created_tiers.clear()
    mock_props.lods.__iter__ = lambda self: iter(created_tiers)
    mock_props.lods.__len__ = lambda self: len(created_tiers)

    # Test reset_to_preset operator
    op_reset = LOD_OT_reset_to_preset()
    assert op_reset.execute(None) == {"FINISHED"}
    assert op_reset.execute(mock_context) == {"FINISHED"}


def test_panel2_modify_collection_first_and_lod0_only(monkeypatch):
    """Verify Panel 2 Modify draws cleanly without selection and operators target LOD0 only."""
    import ui.cleanup_ops as cleanup_ops
    import ui.panel as panel_mod
    import ui.utils as ui_utils
    from ui.cleanup_ops import (
        LOD_OT_apply_all_modifiers,
        LOD_OT_apply_transforms,
        LOD_OT_clean_and_repair_materials,
        LOD_OT_clean_and_repair_mesh,
    )
    from ui.panel import OMNIMESH_PT_modify
    from ui.utils import get_lod0_mesh_objects

    mock_bpy = MagicMock()
    monkeypatch.setattr(ui_utils, "bpy", mock_bpy)
    monkeypatch.setattr(cleanup_ops, "bpy", mock_bpy)
    monkeypatch.setattr(panel_mod, "bpy", mock_bpy)

    # Setup LOD0 mesh and derivative LOD mesh
    mesh_lod0 = MagicMock()
    mesh_lod0.name = "Suzanne"
    mesh_lod0.type = "MESH"
    mesh_lod0.get.return_value = False
    mesh_lod0.data = MagicMock()
    mesh_lod0.data.users = 1
    mesh_lod0.data.shape_keys = None
    mesh_lod0.animation_data = None
    mesh_lod0.material_slots = []

    mesh_lod1 = MagicMock()
    mesh_lod1.name = "Suzanne_LOD1"
    mesh_lod1.type = "MESH"
    mesh_lod1.get.return_value = False

    coll_root = MagicMock()
    coll_root.name = "Suzanne"
    coll_root.objects = [mesh_lod0]

    mock_bpy.data.collections.get.side_effect = lambda name: coll_root if name in {"Suzanne", "Suzanne_LOD0"} else None

    # Context with zero viewport selection
    mock_context = MagicMock()
    mock_context.scene.collection = MagicMock()
    mock_context.active_object = None
    mock_context.selected_objects = []
    mock_props = MagicMock()
    mock_props.active_asset = "Suzanne"
    mock_props.export_base_name = "Suzanne"
    mock_context.scene.lod_tool = mock_props

    # 1. Verify get_lod0_mesh_objects finds LOD0 mesh and excludes derivative LODs
    lod0_meshes = get_lod0_mesh_objects(mock_context)
    assert len(lod0_meshes) == 1
    assert lod0_meshes[0].name == "Suzanne"

    # 2. Verify Panel 2 Modify draws without 'No Mesh Selected' box
    panel_modify = OMNIMESH_PT_modify()
    mock_layout = MagicMock()
    panel_modify.layout = mock_layout
    panel_modify.draw(mock_context)
    assert mock_layout.row.called

    # 3. Verify Operators poll True even with zero selection
    assert LOD_OT_clean_and_repair_mesh.poll(mock_context) is True
    assert LOD_OT_clean_and_repair_materials.poll(mock_context) is True
    assert LOD_OT_apply_all_modifiers.poll(mock_context) is True
    assert LOD_OT_apply_transforms.poll(mock_context) is True
