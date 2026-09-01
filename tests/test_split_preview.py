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
