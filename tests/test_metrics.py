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


def test_distance_and_screen_size_inversion():
    radius = 5.0
    s_target = 0.50
    fov_v = math.radians(60.0)

    dist = compute_distance_from_screen_size(radius, s_target, fov_v)
    s_recomputed = compute_screen_size_from_distance(radius, dist, fov_v)
    assert pytest.approx(s_recomputed, rel=1e-4) == s_target


def test_screen_space_error_bound():
    radius = 10.0
    s = 0.50
    tau_sse = 1.0
    h = 1080

    delta = compute_screen_space_error_bound(radius, s, tau_sse, h)
    # delta = (2 * 1.0 * 10.0) / (0.5 * 1080) = 20 / 540 = 0.037037 m
    expected = 20.0 / 540.0
    assert pytest.approx(delta, rel=1e-4) == expected


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


def test_logarithmic_screen_tiers():
    tiers = generate_logarithmic_screen_tiers(7, 0.5)
    assert len(tiers) == 7
    assert tiers[0] == 100.0
    assert tiers[-1] == 0.5
    # Strictly descending
    for i in range(len(tiers) - 1):
        assert tiers[i] > tiers[i + 1]
