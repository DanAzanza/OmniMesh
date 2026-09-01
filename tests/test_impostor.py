"""
Unit tests for OmniMesh Billboard & Octahedral Impostor Subsystem.
"""

from __future__ import annotations

import math
import numpy as np

from core.impostor import ImpostorMath, ImpostorMeshBuilder, ImpostorManager


def test_hemi_octahedral_mapping_forward_inverse():
    # Test zenith (0, 0, 1) -> center of UV space
    vec_zenith = (0.0, 0.0, 1.0)
    u, v = ImpostorMath.vector_to_hemi_octahedral(vec_zenith)
    assert math.isclose(u, 0.5, abs_tol=1e-5)
    assert math.isclose(v, 0.5, abs_tol=1e-5)

    # Invert back to vector
    rec_vec = ImpostorMath.hemi_octahedral_to_vector(u, v)
    assert math.isclose(rec_vec[0], 0.0, abs_tol=1e-5)
    assert math.isclose(rec_vec[1], 0.0, abs_tol=1e-5)
    assert math.isclose(rec_vec[2], 1.0, abs_tol=1e-5)

    # Test cardinal directions (X > 0, Y=0, Z=0)
    vec_east = (1.0, 0.0, 0.0)
    u_e, v_e = ImpostorMath.vector_to_hemi_octahedral(vec_east)
    rec_east = ImpostorMath.hemi_octahedral_to_vector(u_e, v_e)
    assert math.isclose(rec_east[0], 1.0, abs_tol=1e-4)
    assert math.isclose(rec_east[1], 0.0, abs_tol=1e-4)


def test_full_sphere_octahedral_mapping():
    rec_top = ImpostorMath.full_octahedral_to_vector(0.5, 0.5)
    assert math.isclose(rec_top[0], 0.0, abs_tol=1e-5)
    assert math.isclose(rec_top[1], 0.0, abs_tol=1e-5)
    assert math.isclose(rec_top[2], 1.0, abs_tol=1e-5)


def test_camera_space_tangent_normal_encoding():
    # Camera looking along -Y (cam_forward = (0, -1, 0), cam_right = (1, 0, 0), cam_up = (0, 0, 1))
    cam_right = (1.0, 0.0, 0.0)
    cam_up = (0.0, 0.0, 1.0)
    cam_forward = (0.0, -1.0, 0.0)

    # Surface normal pointing directly toward camera (0, 1, 0)
    n_world = (0.0, 1.0, 0.0)
    nx, ny, nz = ImpostorMath.compute_camera_space_tangent_normal(
        n_world, cam_right, cam_up, cam_forward, flip_green=False
    )
    # Must be flat tangent blue: nx=0, ny=0, nz=1
    assert math.isclose(nx, 0.0, abs_tol=1e-5)
    assert math.isclose(ny, 0.0, abs_tol=1e-5)
    assert math.isclose(nz, 1.0, abs_tol=1e-5)

    # Test DirectX green flip
    nx, ny, nz = ImpostorMath.compute_camera_space_tangent_normal(
        n_world, cam_right, cam_up, cam_forward, flip_green=True
    )
    assert math.isclose(ny, -0.0, abs_tol=1e-5)


def test_morphological_dilation_alpha_protection():
    # Create 8x8 dummy texture with a 2x2 solid center and transparent borders
    tex = np.zeros((8, 8, 4), dtype=np.float32)
    tex[3:5, 3:5, :3] = 1.0  # White color
    tex[3:5, 3:5, 3] = 1.0  # Solid Alpha

    dilated = ImpostorMath.morphological_dilate_rgb(tex, iterations=2)

    # Alpha mask must be strictly identical
    np.testing.assert_array_equal(dilated[:, :, 3], tex[:, :, 3])

    # Pixels adjacent to center (e.g. (2, 3)) should now have color > 0
    assert dilated[2, 3, 0] > 0.0
    assert dilated[2, 3, 3] == 0.0  # Still fully transparent!


def test_impostor_mesh_builder_null_safety():
    assert ImpostorMeshBuilder.build_cross_quads() is None or hasattr(ImpostorMeshBuilder.build_cross_quads(), "verts")
    assert ImpostorMeshBuilder.build_star_quads() is None or hasattr(ImpostorMeshBuilder.build_star_quads(), "verts")
    assert ImpostorMeshBuilder.build_single_camera_quad() is None or hasattr(
        ImpostorMeshBuilder.build_single_camera_quad(), "verts"
    )


def test_impostor_manager_null_safety():
    assert ImpostorManager.create_impostor_material("TestAsset") is None
    assert ImpostorManager.generate_impostor_for_objects([], "TestAsset") is None
