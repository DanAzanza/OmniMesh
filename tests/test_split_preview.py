"""
Unit tests for Visual A/B Split-Screen Viewport Comparison Engine.
"""

from __future__ import annotations

from ui.split_preview import SplitPreviewEngine


def test_split_preview_cache_update():
    SplitPreviewEngine.update_overlay_cache(
        is_active=True,
        split_ratio=0.65,
        left_label="LOD0 Master",
        right_label="LOD4",
        left_tris=45000,
        right_tris=1200,
    )
    cache = SplitPreviewEngine._cached_overlay
    assert cache["is_active"] is True
    assert cache["split_ratio"] == 0.65
    assert cache["left_label"] == "LOD0 Master"
    assert cache["right_label"] == "LOD4"
    assert cache["left_tris"] == 45000
    assert cache["right_tris"] == 1200


def test_split_preview_cache_clamping():
    SplitPreviewEngine.update_overlay_cache(
        is_active=False,
        split_ratio=1.5,
        left_label="A",
        right_label="B",
        left_tris=10,
        right_tris=5,
    )
    assert SplitPreviewEngine._cached_overlay["split_ratio"] == 1.0

    SplitPreviewEngine.update_overlay_cache(
        is_active=False,
        split_ratio=-0.5,
        left_label="A",
        right_label="B",
        left_tris=10,
        right_tris=5,
    )
    assert SplitPreviewEngine._cached_overlay["split_ratio"] == 0.0


def test_split_preview_draw_callback_inactive_safety():
    SplitPreviewEngine.update_overlay_cache(False, 0.5, "", "", 0, 0)
    # Should safely return without crashing even if bpy is not initialized
    SplitPreviewEngine.draw_callback_px()


def test_split_preview_operator_enum_parsing():
    from unittest.mock import MagicMock
    from ui.split_preview import OMNIMESH_OT_toggle_split_preview

    op = OMNIMESH_OT_toggle_split_preview()

    # Mock context and properties
    mock_context = MagicMock()
    mock_props = MagicMock()
    mock_context.scene.lod_tool = mock_props

    # Mock LOD tiers
    tier0 = MagicMock()
    tier0.name = "LOD0"
    tier0.actual_tris = 50000
    tier0.screen_size_pct = 100.0

    tier1 = MagicMock()
    tier1.name = "LOD1"
    tier1.actual_tris = 25000
    tier1.screen_size_pct = 50.0

    tier2 = MagicMock()
    tier2.name = "LOD2"
    tier2.actual_tris = 12000
    tier2.screen_size_pct = 25.0

    mock_props.lods = [tier0, tier1, tier2]
    mock_props.is_split_active = True
    mock_props.split_ratio = 0.5

    # Test string enum "LOD1"
    mock_props.split_compare_tier = "LOD1"
    op.update_split_state(mock_context)
    cache = SplitPreviewEngine._cached_overlay
    assert cache["is_active"] is True
    assert cache["right_label"] == "LOD1 (50.0%)"
    assert cache["right_tris"] == 25000

    # Test string enum "LOD2"
    mock_props.split_compare_tier = "LOD2"
    op.update_split_state(mock_context)
    cache = SplitPreviewEngine._cached_overlay
    assert cache["right_label"] == "LOD2 (25.0%)"
    assert cache["right_tris"] == 12000

    # Test invalid string enum fallback
    mock_props.split_compare_tier = "INVALID"
    op.update_split_state(mock_context)
    cache = SplitPreviewEngine._cached_overlay
    assert cache["right_label"] == "LOD1 (50.0%)"

    # Test int index
    mock_props.split_compare_tier = 2
    op.update_split_state(mock_context)
    cache = SplitPreviewEngine._cached_overlay
    assert cache["right_label"] == "LOD2 (25.0%)"


def test_split_preview_cancel_cleanup():
    from unittest.mock import MagicMock
    from ui.split_preview import OMNIMESH_OT_toggle_split_preview

    op = OMNIMESH_OT_toggle_split_preview()
    mock_context = MagicMock()
    mock_area = MagicMock()
    mock_area.type = "VIEW_3D"
    mock_context.screen.areas = [mock_area]
    res = op.cancel_split(mock_context)
    assert res == {"FINISHED"}
    assert SplitPreviewEngine._cached_overlay["is_active"] is False
    assert mock_area.tag_redraw.called


def test_split_preview_engine_shader_and_draw(monkeypatch):
    from unittest.mock import MagicMock
    import ui.split_preview as sp_mod

    mock_gpu = MagicMock()
    mock_shader = MagicMock()
    mock_gpu.shader.from_builtin.return_value = mock_shader
    mock_batch = MagicMock()
    mock_batch_for_shader = MagicMock(return_value=mock_batch)
    mock_blf = MagicMock()
    mock_bpy = MagicMock()
    mock_region = MagicMock()
    mock_region.width = 1920
    mock_region.height = 1080
    mock_bpy.context.region = mock_region
    mock_bpy.context.preferences.system.ui_scale = 1.0

    monkeypatch.setattr(sp_mod, "gpu", mock_gpu)
    monkeypatch.setattr(sp_mod, "batch_for_shader", mock_batch_for_shader)
    monkeypatch.setattr(sp_mod, "blf", mock_blf)
    monkeypatch.setattr(sp_mod, "bpy", mock_bpy)

    SplitPreviewEngine._cached_shader = None
    shader = SplitPreviewEngine._get_shader()
    assert shader == mock_shader
    # Cached access returns immediately
    assert SplitPreviewEngine._get_shader() == mock_shader

    # Draw callback active
    SplitPreviewEngine.update_overlay_cache(
        is_active=True,
        split_ratio=0.5,
        left_label="LOD0",
        right_label="LOD1",
        left_tris=50000,
        right_tris=25000,
    )
    SplitPreviewEngine.draw_callback_px()
    assert mock_gpu.state.blend_set.call_count >= 2
    assert mock_batch.draw.call_count == 2
    assert mock_blf.draw.call_count == 2

    # Draw callback error recovery
    mock_batch.draw.side_effect = RuntimeError("GPU crash simulation")
    SplitPreviewEngine.draw_callback_px()  # Must not raise


def test_split_preview_engine_registration(monkeypatch):
    from unittest.mock import MagicMock
    import ui.split_preview as sp_mod

    mock_bpy = MagicMock()
    monkeypatch.setattr(sp_mod, "bpy", mock_bpy)

    SplitPreviewEngine._handler = None
    mock_bpy.types.SpaceView3D.draw_handler_add.return_value = "dummy_handler"
    SplitPreviewEngine.register_draw_handler()
    assert SplitPreviewEngine._handler == "dummy_handler"

    # Repeated register is a no-op
    SplitPreviewEngine.register_draw_handler()
    assert mock_bpy.types.SpaceView3D.draw_handler_add.call_count == 1

    # Unregister
    SplitPreviewEngine.unregister_draw_handler()
    assert SplitPreviewEngine._handler is None
    mock_bpy.types.SpaceView3D.draw_handler_remove.assert_called_once_with("dummy_handler", "WINDOW")

    # Safe error handling when add fails
    SplitPreviewEngine._handler = None
    mock_bpy.types.SpaceView3D.draw_handler_add.side_effect = RuntimeError("Add failed")
    SplitPreviewEngine.register_draw_handler()
    assert SplitPreviewEngine._handler is None

    # Safe error handling when remove fails
    SplitPreviewEngine._handler = "faulty_handler"
    mock_bpy.types.SpaceView3D.draw_handler_remove.side_effect = RuntimeError("Remove failed")
    SplitPreviewEngine.unregister_draw_handler()
    assert SplitPreviewEngine._handler is None


def test_split_preview_operator_poll_and_execute(monkeypatch):
    from unittest.mock import MagicMock
    import ui.split_preview as sp_mod
    from ui.split_preview import OMNIMESH_OT_toggle_split_preview

    mock_bpy = MagicMock()
    monkeypatch.setattr(sp_mod, "bpy", mock_bpy)

    op = OMNIMESH_OT_toggle_split_preview()

    # Poll boundary conditions
    assert not op.poll(None)
    mock_context = MagicMock()
    mock_props = MagicMock()
    mock_context.scene.lod_tool = mock_props
    mock_props.lods = []
    assert not op.poll(mock_context)
    t0 = MagicMock(actual_tris=1000, screen_size_pct=100.0)
    t0.name = "LOD0"
    mock_props.lods = [t0]
    assert not op.poll(mock_context)
    t1 = MagicMock(actual_tris=500, screen_size_pct=50.0)
    t1.name = "LOD1"
    mock_props.lods = [t0, t1]
    assert op.poll(mock_context)

    # Execute toggle ON
    mock_props.is_split_active = False
    mock_props.split_ratio = 0.5
    mock_props.split_compare_tier = "LOD1"
    mock_context.window_manager.modal_handler_add = MagicMock()
    op.report = MagicMock()  # type: ignore[assignment]
    res_on = op.execute(mock_context)
    assert res_on == {"RUNNING_MODAL"}
    assert mock_props.is_split_active is True
    assert mock_context.window_manager.modal_handler_add.called

    # Execute toggle OFF
    res_off = op.execute(mock_context)
    assert res_off == {"FINISHED"}
    assert mock_props.is_split_active is False

    # Execute edge cases
    assert op.execute(None) == {"CANCELLED"}


def test_split_preview_operator_modal(monkeypatch):
    from unittest.mock import MagicMock
    import ui.split_preview as sp_mod
    from ui.split_preview import OMNIMESH_OT_toggle_split_preview

    mock_bpy = MagicMock()
    monkeypatch.setattr(sp_mod, "bpy", mock_bpy)

    op = OMNIMESH_OT_toggle_split_preview()
    mock_context = MagicMock()
    mock_props = MagicMock()
    mock_context.scene.lod_tool = mock_props
    mock_props.is_split_active = True
    mock_props.split_ratio = 0.5
    t0 = MagicMock(actual_tris=1000, screen_size_pct=100.0)
    t0.name = "LOD0"
    t1 = MagicMock(actual_tris=500, screen_size_pct=50.0)
    t1.name = "LOD1"
    mock_props.lods = [t0, t1]
    mock_props.split_compare_tier = "LOD1"
    mock_context.region.width = 1000

    # ESC event cancels
    event_esc = MagicMock()
    event_esc.type = "ESC"
    assert op.modal(mock_context, event_esc) == {"FINISHED"}

    # RIGHTMOUSE event cancels
    mock_props.is_split_active = True
    event_rmb = MagicMock()
    event_rmb.type = "RIGHTMOUSE"
    assert op.modal(mock_context, event_rmb) == {"FINISHED"}

    # LEFTMOUSE PRESS near split divider triggers dragging
    mock_props.is_split_active = True
    event_lmb_press = MagicMock()
    event_lmb_press.type = "LEFTMOUSE"
    event_lmb_press.value = "PRESS"
    event_lmb_press.mouse_region_x = 510  # within 30px of 500
    res_drag = op.modal(mock_context, event_lmb_press)
    assert res_drag == {"RUNNING_MODAL"}
    assert op._is_dragging is True

    # MOUSEMOVE while dragging updates split_ratio
    event_move = MagicMock()
    event_move.type = "MOUSEMOVE"
    event_move.mouse_region_x = 750
    res_move = op.modal(mock_context, event_move)
    assert res_move == {"RUNNING_MODAL"}
    assert abs(mock_props.split_ratio - 0.75) < 1e-4
    assert mock_context.region.tag_redraw.called

    # LEFTMOUSE RELEASE stops dragging
    event_lmb_release = MagicMock()
    event_lmb_release.type = "LEFTMOUSE"
    event_lmb_release.value = "RELEASE"
    res_rel = op.modal(mock_context, event_lmb_release)
    assert res_rel == {"PASS_THROUGH"}
    assert op._is_dragging is False


def test_split_preview_update_state_mesh_polygons_fallback():
    from unittest.mock import MagicMock
    from ui.split_preview import OMNIMESH_OT_toggle_split_preview

    op = OMNIMESH_OT_toggle_split_preview()
    mock_context = MagicMock()
    mock_props = MagicMock()
    mock_context.scene.lod_tool = mock_props

    tier0 = MagicMock()
    tier0.actual_tris = 0
    tier0.generated_obj.data.polygons = [MagicMock()] * 1234
    tier1 = MagicMock()
    tier1.actual_tris = 0
    tier1.generated_obj.data.polygons = [MagicMock()] * 567
    tier1.name = "LOD1_Custom"
    tier1.screen_size_pct = 40.0

    mock_props.lods = [tier0, tier1]
    mock_props.split_compare_tier = "LOD1"
    mock_props.is_split_active = True
    mock_props.split_ratio = 0.5

    op.update_split_state(mock_context)
    cache = SplitPreviewEngine._cached_overlay
    assert cache["left_tris"] == 1234
    assert cache["right_tris"] == 567


def test_split_preview_registration_ops(monkeypatch):
    from unittest.mock import MagicMock
    import ui.split_preview as sp_mod
    from ui.split_preview import register_split_ops, unregister_split_ops

    mock_bpy = MagicMock()
    monkeypatch.setattr(sp_mod, "bpy", mock_bpy)

    register_split_ops()
    assert mock_bpy.utils.register_class.called

    unregister_split_ops()
    assert mock_bpy.utils.unregister_class.called
