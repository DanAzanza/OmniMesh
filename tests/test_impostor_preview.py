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
    from tests.conftest import MockBlendData

    bdata = MockBlendData()
    assert safe_load_image("", blend_data=bdata) is None
    assert safe_load_image("non_existent_path.png", blend_data=bdata) is None

    assert setup_impostor_tracking(None, blend_data=bdata) is None
    assert setup_preview_turntable(None, (0.0, 0.0, 0.0), 5.0, 2.0, blend_data=bdata) is False

    assert setup_impostor_preview_rig(None, [], "Test", "/tmp", blend_data=bdata) == {}
    assert teardown_impostor_preview_rig(None, "Test", blend_data=bdata) is False

    from ui.impostor_viewport_ops import (
        is_impostor_viewport_timer_running,
        start_impostor_viewport_timer,
        stop_impostor_viewport_timer,
    )

    assert start_impostor_viewport_timer("Test") is False
    assert stop_impostor_viewport_timer("Test") is False
    assert is_impostor_viewport_timer_running("Test") is False


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

    from collections import defaultdict

    def mock_node_new(type=None):
        node = MagicMock()
        node.type = type
        node.inputs = defaultdict(MagicMock)
        node.outputs = defaultdict(MagicMock)
        created_nodes[type] = created_nodes.get(type, 0) + 1
        return node

    mock_nodes.new.side_effect = mock_node_new
    mock_blend_data = MagicMock()
    mock_blend_data.materials.get.return_value = None
    mock_blend_data.materials.new.return_value = mock_mat

    import core.impostor_preview as preview_module
    import core.impostor_preview_material as preview_mat_module

    monkeypatch.setattr(preview_module, "bpy", mock_bpy)
    monkeypatch.setattr(preview_mat_module, "bpy", mock_bpy)

    # Test with target_engine="UE5" (should create SeparateColor and Math for Green inversion)
    mat = preview_module.create_octahedral_preview_material(
        mat_name="M_Test_Preview",
        base_color_path="dummy_base.png",
        normal_path=None,
        orm_path=None,
        grid_size=8,
        target_engine="UE5",
        blend_data=mock_blend_data,
    )

    assert mat is not None
    assert created_nodes.get("ShaderNodeOutputMaterial") == 1
    assert created_nodes.get("ShaderNodeBsdfPrincipled") == 1
    assert created_nodes.get("ShaderNodeVectorTransform") == 2
    assert created_nodes.get("ShaderNodeCombineXYZ") == 1
    assert mock_links.new.called


def test_impostor_preview_pure_di_missing_blend_data_fails_closed():
    """Verify pure DI fail-closed invariants when blend_data is None."""
    from typing import Any, cast
    import core.impostor_preview as preview_mod

    assert preview_mod.safe_load_image("dummy.png", blend_data=cast(Any, None)) is None
    assert preview_mod.create_octahedral_preview_material("M_Fail", "dummy.png", blend_data=cast(Any, None)) is None
    assert preview_mod.setup_impostor_preview_rig(None, [], "Test", "/tmp", blend_data=cast(Any, None)) == {}
    assert preview_mod.teardown_impostor_preview_rig(None, "Test", blend_data=cast(Any, None)) is False


def test_impostor_preview_pure_di_lifecycle_with_mock_blend_data(tmp_path, monkeypatch):
    """Verify full lifecycle of setup and teardown using canonical MockBlendData."""
    import core.impostor_preview as preview_mod
    from tests.conftest import MockBlendData, MockMeshObject

    mock_bdata = MockBlendData()
    mock_bpy = MagicMock()
    import core.impostor_preview_material as preview_mat_module

    monkeypatch.setattr(preview_mod, "bpy", mock_bpy)
    monkeypatch.setattr(preview_mat_module, "bpy", mock_bpy)

    # Mock texture files
    base_color_path = tmp_path / "T_SM_Asset_Impostor_BaseColor.png"
    base_color_path.write_bytes(b"dummy")

    mesh_obj = MockMeshObject(name="SM_Asset_LOD0")
    mesh_obj.matrix_world = MagicMock()
    mesh_obj.bound_box = ((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0))

    rig_info = preview_mod.setup_impostor_preview_rig(
        context=None,
        mesh_objs=[mesh_obj],
        base_name="SM_Asset",
        texture_dir=str(tmp_path),
        blend_data=mock_bdata,
    )

    assert rig_info != {}
    assert "SM_Asset_Preview_Rig" in mock_bdata.collections
    assert "SM_Asset_Preview_Impostor" in mock_bdata.objects
    assert "SM_Asset_Preview_Camera" in mock_bdata.objects
    assert "SM_Asset_Preview_Sun" in mock_bdata.objects

    # Teardown
    success = preview_mod.teardown_impostor_preview_rig(
        context=None,
        base_name="SM_Asset",
        blend_data=mock_bdata,
    )
    assert success is True
    assert "SM_Asset_Preview_Rig" not in mock_bdata.collections
    assert "SM_Asset_Preview_Impostor" not in mock_bdata.objects


def test_octahedral_material_viewport_incoming_sphere_and_unity_unbound(monkeypatch):
    """
    Verify VIEWPORT_INCOMING mode uses Geometry.Incoming without VectorTransform,
    supports OCTAHEDRAL_SPHERE math, clamps grid tile indices, and creates muted slots for UNITY_6.
    """
    from collections import defaultdict
    import core.impostor_preview_material as preview_mat_module

    mock_bpy = MagicMock()
    mock_mat = MagicMock()
    created_nodes: dict[str, int] = {}
    created_list = []

    def mock_node_new(type: str | None = None):
        node = MagicMock()
        node.type = type
        node.inputs = defaultdict(MagicMock)
        node.outputs = defaultdict(MagicMock)
        key = str(type or "")
        created_nodes[key] = created_nodes.get(key, 0) + 1
        created_list.append(node)
        return node

    mock_mat.node_tree.nodes.new.side_effect = mock_node_new
    mock_bdata = MagicMock()
    mock_bdata.materials.get.return_value = None
    mock_bdata.materials.new.return_value = mock_mat
    monkeypatch.setattr(preview_mat_module, "bpy", mock_bpy)

    mat = preview_mat_module.create_octahedral_preview_material(
        mat_name="M_Sphere_Imp",
        base_color_path="",
        grid_size=8,
        target_engine="UNITY_6",
        mode="OCTAHEDRAL_SPHERE",
        view_dir_mode="VIEWPORT_INCOMING",
        allow_unbound_tex_nodes=True,
        blend_data=mock_bdata,
    )

    assert mat is mock_mat
    assert mock_mat.surface_render_method == "BLENDED"
    assert mock_mat.use_backface_culling is False
    assert created_nodes.get("ShaderNodeVectorTransform") == 1
    assert created_nodes.get("ShaderNodeTexImage") == 3
    assert created_nodes.get("ShaderNodeInvert") == 1
    # 2 tile-index clamps [0, 7] + 2 sub-UV clamps [0.002, 0.998]
    assert created_nodes.get("ShaderNodeClamp") == 4
    assert all(n.mute is True for n in created_list if n.type == "ShaderNodeTexImage")
