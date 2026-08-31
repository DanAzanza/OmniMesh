"""
Unit tests for Real-Time LOD Simulator & Distance Evaluation.
"""

import pytest

from core.simulator import calculate_effective_distance_pure, evaluate_lod_tier_index_pure


def test_effective_near_point_distance():
    cam_pos = (0.0, 10.0, 0.0)
    asset_center = (0.0, 0.0, 0.0)
    radius = 2.0

    # Euclidean center distance = 10.0
    # Near-point conservative distance = max(0.01, 10.0 - 0.5 * 2.0) = 9.0
    d_eff = calculate_effective_distance_pure(cam_pos, asset_center, radius)
    assert d_eff == pytest.approx(9.0, rel=1e-3)


def test_tier_evaluation_standard_thresholds():
    # Thresholds = [100.0, 50.0, 25.0, 10.0, 5.0, 2.0, 0.5]
    # S >= 50.0% -> LOD0
    # 25.0% <= S < 50.0% -> LOD1
    # 10.0% <= S < 25.0% -> LOD2
    # 5.0% <= S < 10.0% -> LOD3
    # 2.0% <= S < 5.0% -> LOD4
    # 0.5% <= S < 2.0% -> LOD5
    # S < 0.5% -> LOD6
    thresholds = [100.0, 50.0, 25.0, 10.0, 5.0, 2.0, 0.5]

    assert evaluate_lod_tier_index_pure(100.0, thresholds) == 0
    assert evaluate_lod_tier_index_pure(60.0, thresholds) == 0
    assert evaluate_lod_tier_index_pure(30.0, thresholds) == 1
    assert evaluate_lod_tier_index_pure(12.0, thresholds) == 2
    assert evaluate_lod_tier_index_pure(7.0, thresholds) == 3
    assert evaluate_lod_tier_index_pure(3.0, thresholds) == 4
    assert evaluate_lod_tier_index_pure(1.0, thresholds) == 5
    assert evaluate_lod_tier_index_pure(0.2, thresholds) == 6


def test_hysteresis_band_switching():
    thresholds = [100.0, 50.0, 25.0, 10.0, 5.0, 2.0, 0.5]

    # If currently at LOD0 (switch to LOD1 is at 50.0%), with 2% hysteresis:
    # It will stay at LOD0 down to 50.0 * 0.98 = 49.0%
    assert evaluate_lod_tier_index_pure(49.5, thresholds, current_tier=0, hysteresis_pct=2.0) == 0
    # Below 49.0% (e.g. 48.5%), it drops to LOD1
    assert evaluate_lod_tier_index_pure(48.5, thresholds, current_tier=0, hysteresis_pct=2.0) == 1

    # If currently at LOD1 (switch back to LOD0 is at 50.0%), with 2% hysteresis:
    # It requires 50.0 * 1.02 = 51.0% to switch back up to LOD0
    assert evaluate_lod_tier_index_pure(50.5, thresholds, current_tier=1, hysteresis_pct=2.0) == 1
    assert evaluate_lod_tier_index_pure(51.5, thresholds, current_tier=1, hysteresis_pct=2.0) == 0
