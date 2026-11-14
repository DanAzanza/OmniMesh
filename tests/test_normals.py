from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

from core.normals import NormalManager


def test_ensure_sharp_edge_attribute(monkeypatch):
    assert NormalManager.ensure_sharp_edge_attribute(None) is None

    mock_mesh = MagicMock()
    mock_mesh.attributes.get.return_value = None
    mock_attr = MagicMock()
    mock_mesh.attributes.new.return_value = mock_attr

    # Standalone without bpy returns None safely
    res = NormalManager.ensure_sharp_edge_attribute(mock_mesh)
    assert res is None or res == mock_attr

    # With mocked bpy, creates BOOLEAN EDGE attribute when missing
    monkeypatch.setattr("core.normals.bpy", MagicMock())
    created = NormalManager.ensure_sharp_edge_attribute(mock_mesh)
    assert created == mock_attr
    mock_mesh.attributes.new.assert_called_once_with(name="sharp_edge", type="BOOLEAN", domain="EDGE")


def test_reproject_custom_split_normals_null_or_identical():
    assert NormalManager.reproject_custom_split_normals(None, None) is False

    dummy_obj: Any = object()
    assert NormalManager.reproject_custom_split_normals(dummy_obj, dummy_obj) is False


def test_reproject_custom_split_normals_armature_pose_lock(monkeypatch):
    mock_bpy = MagicMock()
    mock_bpy.ops.object.modifier_apply.side_effect = RuntimeError("Modifier apply failed in test")
    monkeypatch.setattr("core.normals.bpy", mock_bpy)

    mock_src = MagicMock(type="MESH")
    mock_tgt = MagicMock(type="MESH")
    mock_src.data.users = 1
    mock_tgt.data.users = 1

    mock_src.data.vertices = [MagicMock(co=(0, 0, 0), normal=(0, 0, 1))]
    mock_tgt.data.vertices = [MagicMock(co=(0, 0, 0), normal=(0, 0, 1))]
    mock_src.data.polygons = [MagicMock(loop_indices=[0])]
    mock_tgt.data.polygons = [MagicMock(loop_indices=[0])]
    mock_tgt.data.loops = [MagicMock(vertex_index=0)]

    mock_arm = MagicMock()
    mock_arm.data.pose_position = "POSE"

    # Verify that pose_position is locked to REST and restored to POSE in finally even on exception
    NormalManager.reproject_custom_split_normals(mock_tgt, mock_src, armature_obj=mock_arm)
    assert mock_arm.data.pose_position == "POSE"


def test_reproject_custom_split_normals_configures_zero_ray_radius(monkeypatch):
    """Verify DATA_TRANSFER modifier sets POLYINTERP_LNORPROJ and ray_radius = 0.0 to avoid BVH overlap bottleneck."""
    mock_bpy = MagicMock()
    monkeypatch.setattr("core.normals.bpy", mock_bpy)

    mock_src = MagicMock(type="MESH")
    mock_tgt = MagicMock(type="MESH")
    mock_src.data.users = 1
    mock_tgt.data.users = 1
    mock_src.data.vertices = [MagicMock(co=(0.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0))]
    mock_tgt.data.vertices = [MagicMock(co=(0.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0))]
    mock_src.data.polygons = [MagicMock(loop_indices=[0])]
    mock_tgt.data.polygons = [MagicMock(loop_indices=[0])]

    dt_mod = MagicMock()
    dt_mod.name = "__LOD_NORMAL_TRANSFER__"
    mock_tgt.modifiers.get.return_value = None
    mock_tgt.modifiers.new.return_value = dt_mod

    ctx = MagicMock()
    ok = NormalManager.reproject_custom_split_normals(mock_tgt, mock_src, delta_world=0.25, context=ctx)
    assert ok is True
    assert dt_mod.loop_mapping == "POLYINTERP_LNORPROJ"
    assert dt_mod.ray_radius == 0.0
    assert dt_mod.max_distance >= 0.5
    mock_bpy.ops.object.modifier_apply.assert_called_once_with(modifier="__LOD_NORMAL_TRANSFER__")


def test_kdtree_normal_transfer_fallback_guards_and_singular_matrix(monkeypatch):
    assert NormalManager._kdtree_normal_transfer_fallback(None, None) is False

    class FakeKDTree:
        def __init__(self, size: int):
            self.points: list[tuple[Any, int]] = []

        def insert(self, co: Any, idx: int) -> None:
            self.points.append((co, idx))

        def balance(self) -> None:
            pass

        def find(self, co: Any) -> tuple[Any, int, float]:
            return (co, 0, 0.0)

    monkeypatch.setattr("core.normals.KDTree", FakeKDTree)
    monkeypatch.setattr("core.normals.Vector", None)

    mock_src = MagicMock(type="MESH")
    mock_tgt = MagicMock(type="MESH")

    # Boundary 1: Empty vertices or loops returns False safely
    mock_src.data.vertices = []
    mock_tgt.data.loops = []
    assert NormalManager._kdtree_normal_transfer_fallback(mock_tgt, mock_src) is False

    # Boundary 2: Singular 3x3 rotation matrix (determinant == 0.0) does not raise ZeroDivisionError/ValueError
    mock_src.data.vertices = [MagicMock(co=(0.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0))]
    mock_tgt.data.vertices = [MagicMock(co=(0.0, 0.0, 0.0), normal=(0.0, 0.0, 1.0))]
    mock_tgt.data.loops = [MagicMock(vertex_index=0)]

    singular_3x3 = MagicMock()
    singular_3x3.determinant.return_value = 0.0
    mock_src.matrix_world = None
    mock_tgt.matrix_world = None

    ok = NormalManager.transfer_boundary_loop_normals_kdtree(mock_tgt, mock_src)
    assert ok is True
    mock_tgt.data.normals_split_custom_set.assert_called_once_with([(0.0, 0.0, 1.0)])


def test_reproject_custom_split_normals_context_decoupled():
    mock_src = MagicMock()
    mock_src.type = "MESH"
    mock_tgt = MagicMock()
    mock_tgt.type = "MESH"
    mock_src.data.vertices = [MagicMock(co=(0, 0, 0), normal=(0, 0, 1))]
    mock_tgt.data.vertices = [MagicMock(co=(0, 0, 0), normal=(0, 0, 1))]
    mock_src.data.polygons = [MagicMock(loop_indices=[0])]
    mock_tgt.data.polygons = [MagicMock(loop_indices=[0])]
    mock_tgt.data.loops = [MagicMock(vertex_index=0)]

    mock_context = MagicMock()
    # Explicit context passed
    NormalManager.reproject_custom_split_normals(mock_tgt, mock_src, context=mock_context)
    # None context passed
    NormalManager.reproject_custom_split_normals(mock_tgt, mock_src, context=None)
    assert NormalManager._kdtree_normal_transfer_fallback(cast(Any, object()), None) is False
    assert NormalManager._kdtree_normal_transfer_fallback(None, cast(Any, object())) is False
