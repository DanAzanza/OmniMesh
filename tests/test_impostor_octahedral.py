"""
Unit tests for OmniMesh Pillar 2 Octahedral Impostor & Companion Shaders.
"""

from __future__ import annotations

import math
import os
import tempfile

from core.impostor import ImpostorMath, ImpostorMeshBuilder
from exporters.shaders import export_companion_shaders


def test_camera_basis_computation_polar_stability():
    """Verifies that compute_camera_basis avoids polar singularities and produces orthonormal frames."""
    # 1. Zenith pole (0, 0, 1)
    d_pole = (0.0, 0.0, 1.0)
    right, up, forward = ImpostorMath.compute_camera_basis(d_pole)

    # Forward must be -Z
    assert math.isclose(forward.x, 0.0, abs_tol=1e-5)
    assert math.isclose(forward.y, 0.0, abs_tol=1e-5)
    assert math.isclose(forward.z, -1.0, abs_tol=1e-5)

    # Basis vectors must be non-zero unit vectors
    assert math.isclose(right.length, 1.0, abs_tol=1e-5)
    assert math.isclose(up.length, 1.0, abs_tol=1e-5)

    # Must be mutually perpendicular (dot products == 0)
    assert math.isclose(right.dot(up), 0.0, abs_tol=1e-5)
    assert math.isclose(right.dot(forward), 0.0, abs_tol=1e-5)
    assert math.isclose(up.dot(forward), 0.0, abs_tol=1e-5)

    # 2. Cardinal Horizon (1, 0, 0)
    d_horizon = (1.0, 0.0, 0.0)
    right_h, up_h, fwd_h = ImpostorMath.compute_camera_basis(d_horizon)
    assert math.isclose(right_h.dot(up_h), 0.0, abs_tol=1e-5)
    assert math.isclose(right_h.dot(fwd_h), 0.0, abs_tol=1e-5)
    assert math.isclose(up_h.dot(fwd_h), 0.0, abs_tol=1e-5)

    # 3. Arbitrary diagonal
    val = 1.0 / math.sqrt(3.0)
    d_diag = (val, val, val)
    right_d, up_d, fwd_d = ImpostorMath.compute_camera_basis(d_diag)
    assert math.isclose(right_d.dot(up_d), 0.0, abs_tol=1e-5)
    assert math.isclose(right_d.dot(fwd_d), 0.0, abs_tol=1e-5)
    assert math.isclose(up_d.dot(fwd_d), 0.0, abs_tol=1e-5)


def test_build_octahedral_cutout_polygon():
    """Verifies that the 8-vertex cutout polygon creates an 8-sided face with normalized UVs."""
    min_c = (-2.0, -1.5, 0.0)
    max_c = (2.0, 1.5, 5.0)

    bm = ImpostorMeshBuilder.build_octahedral_cutout_polygon(
        min_coords=min_c,
        max_coords=max_c,
        padding_pct=0.04,
        bevel_pct=0.25,
    )

    if bm is not None:
        try:
            assert len(bm.verts) == 8
            assert len(bm.faces) == 1
            face = bm.faces[0]
            assert len(face.verts) == 8

            uv_layer = bm.loops.layers.uv.verify()
            uvs = [loop[uv_layer].uv for loop in face.loops]
            for u, v in uvs:
                assert 0.0 <= u <= 1.0
                assert 0.0 <= v <= 1.0
        finally:
            bm.free()


def test_companion_shader_generation_and_export():
    """Verifies generation and syntax of Godot, Unity, and Unreal companion shaders."""
    with tempfile.TemporaryDirectory() as temp_dir:
        exported = export_companion_shaders(
            base_name="Hero_Asset",
            output_dir=temp_dir,
            target_engine="ALL",
            grid_size=8,
            alpha_scissor=0.45,
        )

        assert "GODOT" in exported
        assert "UNITY" in exported
        assert "UE5" in exported

        # Verify Godot .gdshader
        godot_file = exported["GODOT"]
        assert os.path.exists(godot_file)
        with open(godot_file, "r", encoding="utf-8") as f:
            godot_src = f.read()
            assert "shader_type spatial;" in godot_src
            assert "uniform vec2 grid_size" in godot_src
            assert "v_local_view_dir" in godot_src
            assert "dir_to_hemi_octa" in godot_src

        # Verify Unity HLSL
        unity_file = exported["UNITY"]
        assert os.path.exists(unity_file)
        with open(unity_file, "r", encoding="utf-8") as f:
            unity_src = f.read()
            assert "OMNIMESH_OCTAHEDRAL_INCLUDED" in unity_src
            assert "DirToHemiOcta_float" in unity_src
            assert "SampleOctahedralImpostor_float" in unity_src

        # Verify Unreal HLSL
        ue5_file = exported["UE5"]
        assert os.path.exists(ue5_file)
        with open(ue5_file, "r", encoding="utf-8") as f:
            ue5_src = f.read()
            assert "Texture2D BaseColorTex" in ue5_src
            assert "LocalViewDir" in ue5_src
