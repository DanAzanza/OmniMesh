"""
Deep unit tests for core/impostor_baker.py.
Tests view angle computation, atlas grid dimension mapping,
atlas compositing with morphological dilation, and Cycles compute device configuration.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import numpy as np

from core.impostor_baker import ImpostorAtlasBaker


def test_get_grid_dimensions():
    assert ImpostorAtlasBaker.get_grid_dimensions("STAR_QUADS") == (2, 2)
    assert ImpostorAtlasBaker.get_grid_dimensions("ORTHO_3_AXES") == (2, 2)
    assert ImpostorAtlasBaker.get_grid_dimensions("OCTAHEDRAL_HEMI") == (8, 8)
    assert ImpostorAtlasBaker.get_grid_dimensions("OCTAHEDRAL_SPHERE") == (8, 8)
    assert ImpostorAtlasBaker.get_grid_dimensions("UNKNOWN_MODE") == (2, 1)


def test_get_view_angles_star_quads_and_ortho():
    angles_star = ImpostorAtlasBaker.get_view_angles_for_mode("STAR_QUADS")
    assert len(angles_star) == 3
    assert angles_star[0] == (0.0, 0.0, (0, 0))
    assert abs(angles_star[1][0] - math.radians(90.0)) < 1e-5

    angles_fallback = ImpostorAtlasBaker.get_view_angles_for_mode("UNKNOWN")
    assert len(angles_fallback) == 2


def test_get_view_angles_octahedral_hemi():
    angles = ImpostorAtlasBaker.get_view_angles_for_mode("OCTAHEDRAL_HEMI")
    assert len(angles) == 64  # 8x8 grid
    for yaw, pitch, (col, row) in angles:
        assert 0 <= col < 8
        assert 0 <= row < 8
        assert -math.pi <= yaw <= math.pi
        # Hemi angles should stay on or above the horizon
        assert pitch >= -1e-5


def test_get_view_angles_octahedral_sphere():
    angles = ImpostorAtlasBaker.get_view_angles_for_mode("OCTAHEDRAL_SPHERE")
    assert len(angles) == 64
    for _yaw, _pitch, (col, row) in angles:
        assert 0 <= col < 8
        assert 0 <= row < 8


def test_compose_atlas_array_no_dilation():
    tile_w, tile_h = 16, 16
    tile_1 = np.full((tile_h, tile_w, 4), 100, dtype=np.uint8)
    tile_2 = np.full((tile_h, tile_w, 4), 200, dtype=np.uint8)

    tiles = [(tile_1, (0, 0)), (tile_2, (1, 0))]
    atlas = ImpostorAtlasBaker.compose_atlas_array(
        tiles=tiles,
        grid_cols=2,
        grid_rows=1,
        tile_w=tile_w,
        tile_h=tile_h,
        dilation_iterations=0,
    )

    assert atlas.shape == (16, 32, 4)
    assert np.all(atlas[:, :16, :] == 100)
    assert np.all(atlas[:, 16:, :] == 200)


def test_compose_atlas_array_with_dilation():
    tile_w, tile_h = 8, 8
    # Center pixel is white, rest is transparent
    tile = np.zeros((tile_h, tile_w, 4), dtype=np.uint8)
    tile[4, 4] = [255, 255, 255, 255]

    atlas = ImpostorAtlasBaker.compose_atlas_array(
        tiles=[(tile, (0, 0))],
        grid_cols=1,
        grid_rows=1,
        tile_w=tile_w,
        tile_h=tile_h,
        dilation_iterations=2,
    )

    assert atlas.shape == (8, 8, 4)
    # Check that dilation expanded color outward
    assert atlas[4, 4, 3] == 255
    # Pixels around center should have color expanded even if alpha was 0
    assert atlas[4, 5, 0] > 0


def test_configure_cycles_compute_device_no_bpy():
    with patch("core.impostor_baker.bpy", None):
        backend, devs = ImpostorAtlasBaker.configure_cycles_compute_device(None)
        assert backend == "CPU"
        assert devs == ["CPU"]


def test_configure_cycles_compute_device_gpu_detected():
    mock_bpy = MagicMock()
    mock_context = MagicMock()
    mock_cycles_addon = MagicMock()
    mock_cpref = mock_cycles_addon.preferences
    mock_cpref.get_device_types.return_value = [("OPTIX", "OptiX"), ("CUDA", "CUDA")]

    mock_dev = MagicMock()
    mock_dev.type = "OPTIX"
    mock_dev.name = "NVIDIA RTX 4090"
    mock_dev.use = False
    mock_cpref.devices = [mock_dev]

    mock_context.preferences.addons = {"cycles": mock_cycles_addon}
    mock_scene = MagicMock()

    with patch("core.impostor_baker.bpy", mock_bpy):
        backend, devs = ImpostorAtlasBaker.configure_cycles_compute_device(mock_scene, mock_context)
        assert backend == "OPTIX"
        assert "NVIDIA RTX 4090" in devs
        assert mock_dev.use is True
        assert mock_scene.cycles.device == "GPU"


def test_configure_cycles_compute_device_fallback_cpu():
    mock_bpy = MagicMock()
    mock_context = MagicMock()
    mock_context.preferences.addons = {}
    mock_scene = MagicMock()

    with patch("core.impostor_baker.bpy", mock_bpy):
        backend, devs = ImpostorAtlasBaker.configure_cycles_compute_device(mock_scene, mock_context)
        assert backend == "CPU"
        assert devs == ["CPU"]
        assert mock_scene.cycles.device == "CPU"


def test_bake_octahedral_animation_atlas_empty_objs():
    bdata = MagicMock()
    res = ImpostorAtlasBaker.bake_octahedral_animation_atlas(
        mesh_objs=[],
        base_name="Tree",
        output_dir="C:/tmp",
        blend_data=bdata,
    )
    assert res == {}
