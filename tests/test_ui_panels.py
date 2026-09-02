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
    LOD_OT_import_pbr_set,
    LOD_OT_inspect_lod0,
    get_associated_armature,
    get_selected_mesh_objects,
    is_object_valid,
)
from ui.panel import (
    PANEL_CLASSES,
    OMNIMESH_PT_batch_sub,
    OMNIMESH_PT_export,
    OMNIMESH_PT_fix_lod0,
    OMNIMESH_PT_import,
    OMNIMESH_PT_inspection_sub,
    OMNIMESH_PT_lods,
    OMNIMESH_PT_optimization_sub,
    register_panel,
    unregister_panel,
)
from ui.properties import register_properties, unregister_properties


def test_panel_class_hierarchy_and_order():
    """Verify panel architecture has correct root panels, subpanels, bl_order, and registration order."""
    # Root Panels
    assert OMNIMESH_PT_import.bl_idname == "OMNIMESH_PT_import"
    assert OMNIMESH_PT_import.bl_category == "OmniMesh"
    assert OMNIMESH_PT_import.bl_order == 0

    assert OMNIMESH_PT_fix_lod0.bl_idname == "OMNIMESH_PT_fix_lod0"
    assert OMNIMESH_PT_fix_lod0.bl_category == "OmniMesh"
    assert OMNIMESH_PT_fix_lod0.bl_order == 1

    assert OMNIMESH_PT_lods.bl_idname == "OMNIMESH_PT_lods"
    assert OMNIMESH_PT_lods.bl_category == "OmniMesh"
    assert OMNIMESH_PT_lods.bl_order == 2

    assert OMNIMESH_PT_export.bl_idname == "OMNIMESH_PT_export"
    assert OMNIMESH_PT_export.bl_category == "OmniMesh"
    assert OMNIMESH_PT_export.bl_order == 3

    # Subpanels
    assert OMNIMESH_PT_inspection_sub.bl_parent_id == "OMNIMESH_PT_lods"
    assert OMNIMESH_PT_inspection_sub.bl_order == 0
    assert OMNIMESH_PT_optimization_sub.bl_parent_id == "OMNIMESH_PT_lods"
    assert OMNIMESH_PT_optimization_sub.bl_order == 1

    assert OMNIMESH_PT_batch_sub.bl_parent_id == "OMNIMESH_PT_export"
    assert OMNIMESH_PT_batch_sub.bl_order == 0

    # Registration tuple (parent-first topological order)
    assert PANEL_CLASSES[0] is OMNIMESH_PT_import
    assert PANEL_CLASSES[1] is OMNIMESH_PT_fix_lod0
    assert PANEL_CLASSES[2] is OMNIMESH_PT_lods
    assert PANEL_CLASSES[5] is OMNIMESH_PT_export
    assert len(PANEL_CLASSES) == 7


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
    assert LOD_OT_generate_all.poll(None) is False

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
