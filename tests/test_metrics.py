"""
Unit tests for LOD Tool mathematical metrics engine.
"""

import math

import pytest

from core.metrics import (
    compute_bounding_sphere,
    compute_coupled_tolerances,
    compute_distance_from_screen_size,
    compute_screen_size_from_distance,
    compute_screen_space_error_bound,
    compute_vertical_fov,
    generate_logarithmic_screen_tiers,
)


def test_vertical_fov_calculation():
    # 16:9 aspect ratio, 90 deg horizontal FOV
    aspect_ratio = 16.0 / 9.0
    fov_h = math.radians(90.0)
    fov_v = compute_vertical_fov(fov_h, aspect_ratio, "HORIZONTAL")

    # tan(fov_v / 2) = tan(45 deg) / (16/9) = 9/16 = 0.5625
    expected_fov_v = 2.0 * math.atan(0.5625)
    assert pytest.approx(fov_v, rel=1e-4) == expected_fov_v


def test_vertical_fov_edge_cases():
    # Vertical fit
    fov_v_input = math.radians(45.0)
    fov_v = compute_vertical_fov(fov_v_input, 16.0 / 9.0, "VERTICAL")
    assert pytest.approx(fov_v, rel=1e-4) == fov_v_input

    # Zero or negative aspect ratio fallback
    fov_fallback = compute_vertical_fov(math.radians(90.0), 0.0, "HORIZONTAL")
    expected_fallback = 2.0 * math.atan(1.0 / (16.0 / 9.0))
    assert pytest.approx(fov_fallback, rel=1e-4) == expected_fallback

    # Auto sensor fit with portrait ratio (< 1.0)
    fov_portrait = compute_vertical_fov(math.radians(60.0), 0.5, "AUTO")
    assert pytest.approx(fov_portrait, rel=1e-4) == math.radians(60.0)

    # Extreme camera angles
    fov_clamped_low = compute_vertical_fov(0.0, 1.0, "VERTICAL")
    assert fov_clamped_low > 0.0
    fov_clamped_high = compute_vertical_fov(math.pi * 2, 1.0, "VERTICAL")
    assert fov_clamped_high < math.pi


def test_bounding_sphere():
    coords = [
        (1.0, 0.0, 0.0),
        (-1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, -1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.0, 0.0, -1.0),
    ]
    center, radius = compute_bounding_sphere(coords)
    assert pytest.approx(center[0], abs=1e-4) == 0.0
    assert pytest.approx(center[1], abs=1e-4) == 0.0
    assert pytest.approx(center[2], abs=1e-4) == 0.0
    assert pytest.approx(radius, abs=1e-4) == 1.0


def test_bounding_sphere_edge_cases():
    # Empty coords
    center_empty, radius_empty = compute_bounding_sphere([])
    assert radius_empty == 1.0

    # Single point
    center_single, radius_single = compute_bounding_sphere([(5.0, 2.0, -1.0)])
    assert pytest.approx(center_single[0], abs=1e-4) == 5.0
    assert pytest.approx(center_single[1], abs=1e-4) == 2.0
    assert pytest.approx(center_single[2], abs=1e-4) == -1.0
    assert radius_single >= 1e-4


def test_distance_and_screen_size_inversion():
    radius = 5.0
    s_target = 0.50
    fov_v = math.radians(60.0)

    dist = compute_distance_from_screen_size(radius, s_target, fov_v)
    s_recomputed = compute_screen_size_from_distance(radius, dist, fov_v)
    assert pytest.approx(s_recomputed, rel=1e-4) == s_target


def test_distance_and_screen_size_clamping():
    # Zero or negative inputs
    dist_zero = compute_distance_from_screen_size(0.0, 0.0, 0.0)
    assert dist_zero > 0.0

    s_zero = compute_screen_size_from_distance(0.0, 0.0, 0.0)
    assert 0.0 <= s_zero <= 1.0

    s_huge_radius = compute_screen_size_from_distance(1000.0, 0.1, math.radians(60.0))
    assert s_huge_radius == 1.0


def test_screen_space_error_bound():
    radius = 10.0
    s = 0.50
    tau_sse = 1.0
    h = 1080

    delta = compute_screen_space_error_bound(radius, s, tau_sse, h)
    expected = 20.0 / 540.0
    assert pytest.approx(delta, rel=1e-4) == expected

    # Edge cases
    delta_zero_r = compute_screen_space_error_bound(0.0, 0.0, 0.0, 0)
    assert delta_zero_r > 0.0


def test_coupled_tolerances():
    radius = 10.0
    s = 0.50
    tau_sse = 1.0
    h = 1080

    tol = compute_coupled_tolerances(radius, s, tau_sse, h)
    assert tol["delta_world"] > 0
    assert tol["epsilon_merge"] == pytest.approx(tol["delta_world"] / 8.0, rel=1e-4)
    assert tol["w_crit"] == tol["delta_world"]
    assert 0.0 < tol["planar_angle_deg"] <= 45.0
    assert tol["area_crit"] == pytest.approx((math.pi / 4.0) * (tol["delta_world"] ** 2), rel=1e-4)
    assert 0.0 < tol["qem_ratio"] <= 1.0


def test_coupled_tolerances_extreme_values():
    # Huge error bound (small curvature radius)
    tol_extreme = compute_coupled_tolerances(
        radius=100.0,
        screen_size_fraction=0.001,
        tau_sse_pixels=10.0,
        screen_height_px=240,
        local_curvature_radius=0.001,
    )
    assert 0.5 <= tol_extreme["planar_angle_deg"] <= 45.0
    assert 0.005 <= tol_extreme["qem_ratio"] <= 1.0
    assert tol_extreme["epsilon_merge"] <= 100.0 * 0.05


def test_logarithmic_screen_tiers():
    tiers = generate_logarithmic_screen_tiers(7, 0.5)
    assert len(tiers) == 7
    assert tiers[0] == 100.0
    assert tiers[-1] == 0.5
    # Strictly descending
    for i in range(len(tiers) - 1):
        assert tiers[i] > tiers[i + 1]


def test_logarithmic_screen_tiers_edge_cases():
    # 1 LOD
    assert generate_logarithmic_screen_tiers(1, 0.5) == [100.0]
    # 0 LODs
    assert generate_logarithmic_screen_tiers(0, 0.5) == [100.0]
    # Extreme cull pct
    tiers_high = generate_logarithmic_screen_tiers(3, 80.0)
    assert tiers_high[0] == 100.0
    assert tiers_high[-1] == 50.0
