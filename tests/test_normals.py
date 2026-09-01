from __future__ import annotations

from unittest.mock import MagicMock

from core.normals import NormalManager


def test_ensure_sharp_edge_attribute():
    assert NormalManager.ensure_sharp_edge_attribute(None) is None

    mock_mesh = MagicMock()
    mock_mesh.attributes.get.return_value = None
    mock_attr = MagicMock()
    mock_mesh.attributes.new.return_value = mock_attr

    # When bpy is not imported (in standalone mock), returns None safely
    # If mock mesh with attributes is passed
    res = NormalManager.ensure_sharp_edge_attribute(mock_mesh)
    assert res is None or res == mock_attr


def test_reproject_custom_split_normals_null_or_identical():
    assert NormalManager.reproject_custom_split_normals(None, None) is False

    dummy_obj = object()
    assert NormalManager.reproject_custom_split_normals(dummy_obj, dummy_obj) is False


def test_reproject_custom_split_normals_armature_pose_lock():
    mock_src = MagicMock()
    mock_src.type = "MESH"
    mock_tgt = MagicMock()
    mock_tgt.type = "MESH"

    mock_src.data.vertices = [MagicMock(co=(0, 0, 0), normal=(0, 0, 1))]
    mock_tgt.data.vertices = [MagicMock(co=(0, 0, 0), normal=(0, 0, 1))]
    mock_src.data.polygons = [MagicMock(loop_indices=[0])]
    mock_tgt.data.polygons = [MagicMock(loop_indices=[0])]
    mock_tgt.data.loops = [MagicMock(vertex_index=0)]

    mock_arm = MagicMock()
    mock_arm.data.pose_position = "POSE"

    # Testing that it restores pose_position even if bpy ops fails
    NormalManager.reproject_custom_split_normals(mock_tgt, mock_src, armature_obj=mock_arm)
    assert mock_arm.data.pose_position == "POSE"


def test_kdtree_normal_transfer_fallback_guards():
    assert NormalManager._kdtree_normal_transfer_fallback(None, None) is False
    assert NormalManager._kdtree_normal_transfer_fallback(object(), None) is False
    assert NormalManager._kdtree_normal_transfer_fallback(None, object()) is False
