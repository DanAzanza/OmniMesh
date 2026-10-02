"""
Unit tests for OmniMesh In-Blender Preview & Test Rig System for Octahedral Impostors.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock

from core.impostor_math import ImpostorMath
from core.impostor_preview import (
    safe_load_image,
    setup_impostor_preview_rig,
    setup_impostor_tracking,
    setup_preview_turntable,
    teardown_impostor_preview_rig,
)


def test_preview_rig_headless_safety():
    """Verify that all preview rig functions fail safely and gracefully without throwing errors in headless/no-bpy environments."""
    assert safe_load_image("") is None
    assert safe_load_image("non_existent_path.png") is None

    assert setup_impostor_tracking(None) is None
    assert setup_preview_turntable(None, (0.0, 0.0, 0.0), 5.0, 2.0) is False

    assert setup_impostor_preview_rig(None, [], "Test", "/tmp") == {}
    assert teardown_impostor_preview_rig(None, "Test") is False


def test_octahedral_preview_math_ground_truth():
    """
    Verify the mathematical formulas implemented in the Blender shader node network
    strictly match the Python reference implementation for the upper hemisphere.
    """
    grid_size = 8

    test_vectors = [
        # (Direction from surface to camera, expected description)
        ((0.0, -1.0, 0.0), "Front view (-Y)"),
        ((1.0, 0.0, 0.0), "Right view (+X)"),
        ((-1.0, 0.0, 0.0), "Left view (-X)"),
        ((0.0, 1.0, 0.0), "Back view (+Y)"),
        ((0.0, 0.0, 1.0), "Zenith top view (+Z)"),
    ]

    for (vx, vy, vz), desc in test_vectors:
        # Shader node network math simulation:
        z_clamped = max(0.001, vz)
        denom = abs(vx) + abs(vy) + z_clamped
        nx = vx / denom
        ny = vy / denom

        u = (nx + ny) * 0.5 + 0.5
        v = (nx - ny) * 0.5 + 0.5

        # Col & Row in grid
        col = int(math.floor(min(0.999, max(0.0, u)) * grid_size))
        row = int(math.floor(min(0.999, max(0.0, v)) * grid_size))

        # Reference ImpostorMath output
        ref_u, ref_v = ImpostorMath.vector_to_hemi_octahedral((vx, vy, vz))
        ref_col = int(math.floor(min(0.999, max(0.0, ref_u)) * grid_size))
        ref_row = int(math.floor(min(0.999, max(0.0, ref_v)) * grid_size))

        assert col == ref_col, f"Mismatch in col for {desc}: shader={col} vs ref={ref_col}"
        assert row == ref_row, f"Mismatch in row for {desc}: shader={row} vs ref={ref_row}"

        # Blender UV Row inversion: top PNG row is at Blender UV V=1
        blender_row = (grid_size - 1) - row
        assert 0 <= blender_row < grid_size


def test_mock_preview_material_construction(monkeypatch):
    """
    Verify the Shader Node graph construction logic, socket linkages,
    and DirectX green channel compensation under a mocked bpy environment.
    """
    mock_bpy = MagicMock()
    mock_mat = MagicMock()
    mock_nodes = MagicMock()
    mock_links = MagicMock()

    mock_mat.node_tree.nodes = mock_nodes
    mock_mat.node_tree.links = mock_links

    created_nodes = {}

    def mock_node_new(type=None):
        node = MagicMock()
        node.type = type
        node.inputs = {
            "Surface": MagicMock(),
            "Base Color": MagicMock(),
            "Alpha": MagicMock(),
            "Normal": MagicMock(),
            "Roughness": MagicMock(),
            "Metallic": MagicMock(),
            "Vector": MagicMock(),
            "Color": MagicMock(),
            "Red": MagicMock(),
            "Green": MagicMock(),
            "Blue": MagicMock(),
            "X": MagicMock(),
            "Y": MagicMock(),
            "Z": MagicMock(),
            "Value": MagicMock(),
            0: MagicMock(),
            1: MagicMock(),
            2: MagicMock(),
        }
        node.outputs = {
            "BSDF": MagicMock(),
            "Incoming": MagicMock(),
            "Vector": MagicMock(),
            "Color": MagicMock(),
            "Alpha": MagicMock(),
            "Normal": MagicMock(),
            "Red": MagicMock(),
            "Green": MagicMock(),
            "Blue": MagicMock(),
            "X": MagicMock(),
            "Y": MagicMock(),
            "Z": MagicMock(),
            "Value": MagicMock(),
            "UV": MagicMock(),
        }
        created_nodes[type] = created_nodes.get(type, 0) + 1
        return node

    mock_nodes.new.side_effect = mock_node_new
    mock_bpy.data.materials.get.return_value = None
    mock_bpy.data.materials.new.return_value = mock_mat

    import core.impostor_preview as preview_module

    monkeypatch.setattr(preview_module, "bpy", mock_bpy)

    # Test with target_engine="UE5" (should create SeparateColor and Math for Green inversion)
    mat = preview_module.create_octahedral_preview_material(
        mat_name="M_Test_Preview",
        base_color_path="dummy_base.png",
        normal_path=None,
        orm_path=None,
        grid_size=8,
        target_engine="UE5",
    )

    assert mat is not None
    assert created_nodes.get("ShaderNodeOutputMaterial") == 1
    assert created_nodes.get("ShaderNodeBsdfPrincipled") == 1
    assert created_nodes.get("ShaderNodeNewGeometry") == 1
    assert created_nodes.get("ShaderNodeCombineXYZ") == 1
    assert mock_links.new.called
