"""
Unit tests for OmniMesh PBR Impostor Baking Engine and Ephemeral Scene Rig.
"""

from __future__ import annotations

import math
import numpy as np

from core.impostor_baker import (
    EphemeralBakeSceneGuard,
    ImpostorCameraRig,
    ImpostorShaderHarness,
    ImpostorAtlasBaker,
)


def test_impostor_camera_rig_bounds():
    # Symmetric 2x2x2 cube
    coords = [
        (-1.0, -1.0, -1.0),
        (1.0, 1.0, 1.0),
        (-1.0, 1.0, -1.0),
        (1.0, -1.0, 1.0),
    ]
    center, radius, ortho_scale = ImpostorCameraRig.compute_rig_parameters(coords)

    # Radius of unit-cube corners is sqrt(3) ~= 1.732
    assert math.isclose(radius, math.sqrt(3.0), rel_tol=1e-3)
    # Ortho scale must be 2.0 * radius * 1.04
    expected_scale = 2.0 * math.sqrt(3.0) * 1.04
    assert math.isclose(ortho_scale, expected_scale, rel_tol=1e-3)
    # Center should be at origin
    assert math.isclose(center[0], 0.0, abs_tol=1e-5)
    assert math.isclose(center[1], 0.0, abs_tol=1e-5)
    assert math.isclose(center[2], 0.0, abs_tol=1e-5)


def test_impostor_atlas_grid_layouts():
    # Cross Quads (2 views, 2x1 grid)
    cross_angles = ImpostorAtlasBaker.get_view_angles_for_mode("CROSS_QUADS")
    assert len(cross_angles) == 2
    assert ImpostorAtlasBaker.get_grid_dimensions("CROSS_QUADS") == (2, 1)

    # Star Quads & Ortho 3 Axes (3 views, 2x2 grid)
    star_angles = ImpostorAtlasBaker.get_view_angles_for_mode("STAR_QUADS")
    assert len(star_angles) == 3
    assert ImpostorAtlasBaker.get_grid_dimensions("STAR_QUADS") == (2, 2)
    ortho_angles = ImpostorAtlasBaker.get_view_angles_for_mode("ORTHO_3_AXES")
    assert len(ortho_angles) == 3
    assert ImpostorAtlasBaker.get_grid_dimensions("ORTHO_3_AXES") == (2, 2)

    # Octahedral (64 views, 8x8 grid)
    octa_angles = ImpostorAtlasBaker.get_view_angles_for_mode("OCTAHEDRAL_HEMI")
    assert len(octa_angles) == 64
    assert ImpostorAtlasBaker.get_grid_dimensions("OCTAHEDRAL_HEMI") == (8, 8)


def test_impostor_atlas_tile_composition_and_dilation():
    # 2 tiles in 2x1 grid, each 8x8 px
    tile_a = np.zeros((8, 8, 4), dtype=np.uint8)
    tile_a[3:5, 3:5, 0] = 255  # Red center
    tile_a[3:5, 3:5, 3] = 255  # Opaque alpha

    tile_b = np.zeros((8, 8, 4), dtype=np.uint8)
    tile_b[3:5, 3:5, 1] = 255  # Green center
    tile_b[3:5, 3:5, 3] = 255  # Opaque alpha

    tiles = [(tile_a, (0, 0)), (tile_b, (1, 0))]

    atlas = ImpostorAtlasBaker.compose_atlas_array(
        tiles, grid_cols=2, grid_rows=1, tile_w=8, tile_h=8, dilation_iterations=2
    )

    # Total atlas must be 8h x 16w
    assert atlas.shape == (8, 16, 4)
    # Left tile has dilated red
    assert atlas[3, 3, 0] == 255
    # Right tile has dilated green
    assert atlas[3, 11, 1] == 255
    # No cross-talk: right tile does not have red
    assert atlas[3, 11, 0] == 0


def test_impostor_baker_null_safety():
    # Verify headless execution without blender runs cleanly without crashing
    guard = EphemeralBakeSceneGuard()
    with guard as scene:
        assert scene is None

    cam = ImpostorCameraRig.setup_camera(None, (0, 0, 0), 1.0, 2.0)
    assert cam is None

    mat = ImpostorShaderHarness.create_unlit_override_material(None)
    assert mat is None

    res = ImpostorAtlasBaker.bake_impostor_textures([], "TestAsset", "/tmp")
    assert res == {}


def test_morphological_dilate_channels_preserves_zero_depth():
    from core.impostor_math import ImpostorMath

    # 8x8 image with 4 channels (Normal RGB + Depth A)
    img = np.zeros((8, 8, 4), dtype=np.uint8)
    # Put a 2x2 object in the center with Normals (128, 128, 255) and Depth 0
    img[3:5, 3:5, 0] = 128
    img[3:5, 3:5, 1] = 128
    img[3:5, 3:5, 2] = 255
    img[3:5, 3:5, 3] = 0  # Crucial: surface point at closest distance (Depth = 0)

    # BaseColor opacity mask is True for this 2x2 square
    mask = np.zeros((8, 8), dtype=bool)
    mask[3:5, 3:5] = True

    # Dilate 2 iterations
    dilated = ImpostorMath.morphological_dilate_channels(img, mask, iterations=2)

    # 1. The original center pixels MUST still be Depth = 0 (not erased!)
    assert dilated[3, 3, 3] == 0
    assert dilated[4, 4, 3] == 0
    assert dilated[3, 3, 2] == 255

    # 2. Adjacent pixels (e.g. [2, 3]) should now be filled with neighbor values
    assert dilated[2, 3, 2] == 255
    assert dilated[2, 3, 3] == 0


def test_impostor_harness_depth_and_reexport():
    from core.impostor_harness import ImpostorShaderHarness as HarnessDirect
    from core.impostor_baker import ImpostorShaderHarness as HarnessReexport

    # Confirm backward compatibility of re-export
    assert HarnessDirect is HarnessReexport

    # Headless calls should return None safely
    assert HarnessDirect.create_unlit_override_material(None, channel_layer="DEPTH") is None
    assert HarnessDirect.create_unlit_override_material(None, channel_layer="NORMAL", target_engine="UE5") is None


def test_ue5_setup_guide_generation():
    from exporters.shaders.unreal_octahedral import generate_ue5_setup_guide

    guide = generate_ue5_setup_guide(
        base_name="Sedan_Car",
        grid_size=8,
        sphere_radius=2.5,
        sphere_center=(0.0, 0.0, 1.25),
    )

    assert "Asset: Sedan_Car" in guide
    assert "Grid Size: 8x8" in guide
    assert "Bounding Sphere Radius: 2.5000" in guide
    assert "Pixel Depth Offset = Normal.A * 5.0000" in guide
    assert "TC_Default" in guide
    assert "Normalmap (TC_Normalmap / BC5)" in guide
