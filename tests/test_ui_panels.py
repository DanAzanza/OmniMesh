"""
Unit tests for OmniMesh UI subpanels, UIList components, and operator helpers.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from ui.hud import LODViewportHUD
from ui.lists import LOD_UL_tier_list, register_lists, unregister_lists
from ui.operators import get_associated_armature, get_selected_mesh_objects, is_object_valid
from ui.panel import (
    PANEL_CLASSES,
    LOD_PT_batch_panel,
    LOD_PT_export_bridge_panel,
    LOD_PT_inspection_panel,
    LOD_PT_main_panel,
    LOD_PT_optimization_panel,
    LOD_PT_tiers_panel,
    register_panel,
    unregister_panel,
)
from ui.properties import register_properties, unregister_properties


def test_panel_class_hierarchy_and_order():
    """Verify subpanel definitions have correct bl_parent_id, bl_order, and registration order."""
    assert LOD_PT_main_panel.bl_idname == "LOD_PT_main_panel"
    assert LOD_PT_main_panel.bl_category == "OmniMesh"

    # Subpanels must reference LOD_PT_main_panel as parent
    assert LOD_PT_tiers_panel.bl_parent_id == "LOD_PT_main_panel"
    assert LOD_PT_inspection_panel.bl_parent_id == "LOD_PT_main_panel"
    assert LOD_PT_optimization_panel.bl_parent_id == "LOD_PT_main_panel"
    assert LOD_PT_export_bridge_panel.bl_parent_id == "LOD_PT_main_panel"
    assert LOD_PT_batch_panel.bl_parent_id == "LOD_PT_main_panel"

    # Subpanel ordering must be strictly monotonic
    assert LOD_PT_tiers_panel.bl_order == 0
    assert LOD_PT_inspection_panel.bl_order == 1
    assert LOD_PT_optimization_panel.bl_order == 2
    assert LOD_PT_export_bridge_panel.bl_order == 3
    assert LOD_PT_batch_panel.bl_order == 4

    # Registration tuple must start with root parent
    assert PANEL_CLASSES[0] is LOD_PT_main_panel
    assert len(PANEL_CLASSES) == 6


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
    mock_mesh2.type = "MESH"
    mock_mesh2.parent = None
    mock_mod = MagicMock()
    mock_mod.type = "ARMATURE"
    mock_mod.object = mock_armature
    mock_mesh2.modifiers = [mock_mod]

    assert get_associated_armature([mock_mesh2]) == mock_armature


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
