"""
Unit tests for OmniMesh Interactive LOD Distance Scrubber & Viewport Evaluation.
Tests distance-to-screen-size calculation, differential visibility updating,
non-destructive snapshot restoration, and headless execution resilience.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.simulator import (
    LODAssetRecord,
    LODSimulatorEngine,
    calculate_effective_distance_pure,
    evaluate_lod_tier_index_pure,
)


class MockObject:
    """Mock Blender Object with hide_get / hide_set tracking."""

    def __init__(self, name: str, poly_count: int = 100, hidden: bool = False):
        self.name = name
        self.type = "MESH"
        self._hidden = hidden
        self.hide_calls: list[bool] = []
        self.data = MagicMock()
        self.data.polygons = [object()] * poly_count
        self.matrix_world = MagicMock()

    def hide_get(self, view_layer: object = None) -> bool:
        return self._hidden

    def hide_set(self, state: bool, view_layer: object = None) -> None:
        if self._hidden != state:
            self._hidden = state
            self.hide_calls.append(state)


class MockCollection:
    def __init__(self, name: str, objects: list[MockObject]):
        self.name = name
        self.objects = objects

    def get(self, key: str, default: object = None) -> object:
        return default


def test_calculate_effective_distance_pure():
    """Verify conservative near-point distance logic."""
    cam_pos = (0.0, 100.0, 0.0)
    center = (0.0, 0.0, 0.0)
    radius = 20.0
    # d_eff = max(0.01, 100.0 - 0.5 * 20.0) = 90.0
    dist = calculate_effective_distance_pure(cam_pos, center, radius)
    assert pytest.approx(dist, 0.01) == 90.0

    # Negative / NaN protection
    assert calculate_effective_distance_pure((float("nan"), 0, 0), center, radius) == 0.01


def test_evaluate_lod_tier_index_pure():
    """Verify tiered hysteresis screen coverage switching."""
    thresholds = [100.0, 50.0, 25.0, 10.0]

    # At 80% screen size -> LOD0
    assert evaluate_lod_tier_index_pure(80.0, thresholds, current_tier=0) == 0
    # At 40% screen size -> LOD1
    assert evaluate_lod_tier_index_pure(40.0, thresholds, current_tier=0) == 1
    # At 15% screen size -> LOD2
    assert evaluate_lod_tier_index_pure(15.0, thresholds, current_tier=0) == 2
    # At 5% screen size -> LOD3 (terminal)
    assert evaluate_lod_tier_index_pure(5.0, thresholds, current_tier=0) == 3


def test_distance_scrub_differential_visibility_and_snapshot():
    """Verify that distance scrubber applies differential visibility and non-destructively

    restores initial state on return to 0.0m.
    """
    # 1. Setup mock assets
    obj_lod0 = MockObject("Hero_LOD0", poly_count=1000, hidden=False)
    obj_lod1 = MockObject("Hero_LOD1", poly_count=500, hidden=True)
    obj_lod2 = MockObject("Hero_LOD2", poly_count=200, hidden=True)

    record = LODAssetRecord("Hero_Asset", "Hero_Asset")
    record.is_valid = True
    record.radius = 5.0
    record.tier_screen_pcts = [100.0, 50.0, 20.0]
    record.tier_objects = {
        0: [obj_lod0],
        1: [obj_lod1],
        2: [obj_lod2],
    }
    record.current_tier = 0

    LODSimulatorEngine._tracked_assets = {"Hero_Asset": record}
    LODSimulatorEngine._visibility_snapshot = {}

    # Initial mock context
    mock_context = MagicMock()
    mock_context.scene = MagicMock()
    mock_context.view_layer = MagicMock()
    mock_context.active_object = obj_lod0
    mock_context.window_manager.windows = []
    mock_context.screen = None

    # Mock bpy.data.objects
    mock_objects_dict = {
        "Hero_LOD0": obj_lod0,
        "Hero_LOD1": obj_lod1,
        "Hero_LOD2": obj_lod2,
    }

    import core.simulator as sim_mod

    orig_bpy = sim_mod.bpy
    mock_bpy = MagicMock()
    mock_bpy.data.objects.get.side_effect = lambda n: mock_objects_dict.get(n)
    sim_mod.bpy = mock_bpy

    try:
        # Step A: Scrub to a close distance (e.g. 5m -> LOD0)
        res_close = LODSimulatorEngine.evaluate_distance_scrub(mock_context, distance_m=5.0)
        assert res_close["root_name"] == "Hero_Asset"
        assert res_close["current_tier"] == 0
        assert obj_lod0.hide_get() is False
        assert obj_lod1.hide_get() is True
        assert obj_lod2.hide_get() is True

        # Verify snapshot was recorded
        assert "Hero_LOD0" in LODSimulatorEngine._visibility_snapshot
        assert LODSimulatorEngine._visibility_snapshot["Hero_LOD0"] is False
        assert LODSimulatorEngine._visibility_snapshot["Hero_LOD1"] is True

        # Step B: Scrub to distant range (e.g. 150m -> LOD2)
        res_far = LODSimulatorEngine.evaluate_distance_scrub(mock_context, distance_m=150.0)
        assert res_far["current_tier"] == 2
        assert obj_lod0.hide_get() is True
        assert obj_lod1.hide_get() is True
        assert obj_lod2.hide_get() is False

        # Step C: Return to 0.0m (Scrub reset)
        res_reset = LODSimulatorEngine.evaluate_distance_scrub(mock_context, distance_m=0.0)
        assert res_reset == {}
        # Snapshot must be cleared and original visibility restored
        assert len(LODSimulatorEngine._visibility_snapshot) == 0
        assert obj_lod0.hide_get() is False
        assert obj_lod1.hide_get() is True
        assert obj_lod2.hide_get() is True

    finally:
        sim_mod.bpy = orig_bpy
        LODSimulatorEngine._tracked_assets.clear()
        LODSimulatorEngine._visibility_snapshot.clear()


def test_distance_scrub_headless_safety():
    """Verify evaluate_distance_scrub handles None/headless contexts without throwing errors."""
    import core.simulator as sim_mod

    orig_bpy = sim_mod.bpy
    sim_mod.bpy = MagicMock()
    try:
        # None context
        assert LODSimulatorEngine.evaluate_distance_scrub(None, distance_m=50.0) == {}

        # Context with no scene
        ctx_no_scene = MagicMock()
        ctx_no_scene.scene = None
        assert LODSimulatorEngine.evaluate_distance_scrub(ctx_no_scene, distance_m=50.0) == {}
    finally:
        sim_mod.bpy = orig_bpy
