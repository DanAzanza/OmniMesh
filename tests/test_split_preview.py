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
    res = op.cancel_split(mock_context)
    assert res == {"FINISHED"}
    assert SplitPreviewEngine._cached_overlay["is_active"] is False
