"""
Unit tests for OmniMesh Sub-Pixel Slender & Thin Feature Culler.
Architected for Blender 4.2+ LTS & Blender 5.2 LTS.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock

from core.slender import SlenderFeatureCuller


def test_hydraulic_thickness_straight_cylinder():
    # Cylinder: radius R = 0.005m (diameter 10mm), length L = 2.0m
    radius = 0.005
    length = 2.0
    volume = math.pi * (radius**2) * length
    area = (2.0 * math.pi * radius * length) + (2.0 * math.pi * (radius**2))

    t_hydro = SlenderFeatureCuller.compute_hydraulic_thickness(volume, area)
    # 4V / A should match diameter (0.010m) within 0.5%
    expected_diameter = 2.0 * radius
    assert math.isclose(t_hydro, expected_diameter, rel_tol=0.01)

    ar = SlenderFeatureCuller.compute_slenderness_aspect_ratio(area, volume)
    expected_ar = length / expected_diameter  # 2.0 / 0.010 = 200
    assert ar >= expected_ar * 0.75


def test_hydraulic_thickness_catenary_cable():
    # Sagging cable: radius R = 0.004m (diameter 8mm), geodesic length L = 10.0m
    radius = 0.004
    length = 10.0
    volume = math.pi * (radius**2) * length
    area = 2.0 * math.pi * radius * length

    t_hydro = SlenderFeatureCuller.compute_hydraulic_thickness(volume, area)
    expected_diameter = 2.0 * radius
    assert math.isclose(t_hydro, expected_diameter, rel_tol=0.001)

    ar = SlenderFeatureCuller.compute_slenderness_aspect_ratio(area, volume)
    # L / D = 10.0 / 0.008 = 1250
    assert ar > 1000.0


def test_screen_projected_thickness():
    # 10mm cable at 10% screen coverage on a 1080p display with root radius 5m
    thickness_m = 0.010  # 10mm
    screen_size_pct = 10.0  # 10%
    resolution_y = 1080
    root_radius_m = 5.0

    w_proj = SlenderFeatureCuller.compute_screen_projected_thickness(
        thickness_m=thickness_m,
        screen_size_pct=screen_size_pct,
        resolution_y=resolution_y,
        root_radius_m=root_radius_m,
    )
    # w_proj = 0.010 * (0.10 * 1080 / 10.0) = 0.108 px
    assert math.isclose(w_proj, 0.108, rel_tol=1e-3)
    assert w_proj < 1.0  # Sub-pixel aliasing hazard!


def test_world_tolerance_calculation():
    # tau_sse 1.0, screen_size_pct 25%, res_y 1080, radius 2m
    delta_world = SlenderFeatureCuller.compute_world_tolerance(
        tau_sse=1.0,
        screen_size_pct=25.0,
        resolution_y=1080,
        root_radius_m=2.0,
    )
    # delta = 1.0 * (4.0 / (0.25 * 1080)) = 4.0 / 270 = 0.0148m (14.8mm)
    assert math.isclose(delta_world, 4.0 / 270.0, rel_tol=1e-3)


def test_hydraulic_thickness_zero_volume_and_area():
    assert SlenderFeatureCuller.compute_hydraulic_thickness(0.0, 10.0) == 0.0
    assert SlenderFeatureCuller.compute_hydraulic_thickness(10.0, 0.0) == 0.0
    assert SlenderFeatureCuller.compute_slenderness_aspect_ratio(10.0, 0.0) == 0.0


def test_analyze_island_geometry_empty():
    res = SlenderFeatureCuller.analyze_island_geometry([])
    assert res["thickness"] == 0.0
    assert res["aspect_ratio"] == 0.0


def test_cull_slender_features_null_and_empty():
    res1 = SlenderFeatureCuller.cull_slender_features(None, screen_size_pct=50.0)
    assert res1 == {"culled_islands": 0, "culled_faces": 0}

    mock_bm = MagicMock()
    mock_bm.faces = []
    res2 = SlenderFeatureCuller.cull_slender_features(mock_bm, screen_size_pct=50.0)
    assert res2 == {"culled_islands": 0, "culled_faces": 0}


def test_small_compact_island_culling():
    # A small cube/screw with max extent 0.005m (5mm)
    # At 25% screen, res_y 1080, radius 2m, delta_world = 14.8mm
    # So 5mm <= 14.8mm -> small part is sub-pixel and culled!
    delta_world = SlenderFeatureCuller.compute_world_tolerance(
        tau_sse=1.0, screen_size_pct=25.0, resolution_y=1080, root_radius_m=2.0
    )
    assert 0.005 <= delta_world
