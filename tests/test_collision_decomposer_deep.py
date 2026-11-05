"""
Comprehensive deep unit tests for core/collision_decomposer.py
Tests SVD splitting plane calculations, concavity measurement, hull hardening,
vertex budget clamping, and multi-convex decomposition with edge cases.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from core.collision_decomposer import CollisionDecomposer
from core.compat import Vector


class MockBMFace:
    def __init__(self, index: int = 0, center: tuple[float, float, float] = (0.0, 0.0, 0.0)):
        self.index = index
        self.center = center
        self.is_valid = True

    def calc_center_median(self) -> Vector:
        return Vector(self.center)


class MockBMFaces:
    def __init__(self, count: int = 4):
        self.faces = [MockBMFace(i, (float(i), float(i), 0.0)) for i in range(count)]

    def __len__(self) -> int:
        return len(self.faces)

    def __iter__(self):
        return iter(self.faces)

    def __getitem__(self, idx: int) -> MockBMFace:
        return self.faces[idx]

    def ensure_lookup_table(self) -> None:
        pass


class MockBMVerts:
    def __init__(self, count: int = 8):
        self.verts = [MagicMock(co=Vector((float(i), 0.0, 0.0)), is_valid=True) for i in range(count)]

    def __len__(self) -> int:
        return len(self.verts)

    def __iter__(self):
        return iter(self.verts)

    def __getitem__(self, idx: int | slice):
        return self.verts[idx]

    def ensure_lookup_table(self) -> None:
        pass


class MockBMVert:
    def __init__(self, co: Any = None):
        self.co = co or Vector((0.0, 0.0, 0.0))
        self.is_valid = True


class MockBMEdge:
    def __init__(self, length: float = 1.0):
        self.is_valid = True
        self._length = length

    def calc_length(self) -> float:
        return self._length


class MockBMEdges:
    def __init__(self, count: int = 12):
        self.edges = [MockBMEdge(float(i + 1)) for i in range(count)]

    def __len__(self) -> int:
        return len(self.edges)

    def __iter__(self):
        return iter(self.edges)

    def __getitem__(self, idx: int | slice):
        return self.edges[idx]

    def ensure_lookup_table(self) -> None:
        pass


class MockBMesh:
    def __init__(self, vert_count: int = 8, face_count: int = 6):
        self.verts = MockBMVerts(vert_count)
        self.faces = MockBMFaces(face_count)
        self.edges = MockBMEdges(12)

    def copy(self) -> MockBMesh:
        return MockBMesh(len(self.verts), len(self.faces))

    def from_mesh(self, mesh: Any) -> None:
        pass

    def to_mesh(self, mesh: Any) -> None:
        pass

    def free(self) -> None:
        pass


class MockBVHTree:
    def __init__(self, dist: float = 0.05):
        self.dist = dist

    @classmethod
    def FromBMesh(cls, bm: Any, epsilon: float = 1e-5) -> MockBVHTree | None:
        return cls()

    def find_nearest(self, pt: Any) -> tuple[Any, Any, Any, float]:
        return (Vector((0.0, 0.0, 0.0)), Vector((0.0, 0.0, 1.0)), 0, self.dist)


class MockMesh:
    def __init__(self, poly_count: int = 12):
        self.polygons = [MagicMock() for _ in range(poly_count)]
        self.vertices = [MagicMock(co=Vector((float(i), 0.0, 0.0))) for i in range(8)]


class MockObject:
    def __init__(self, name: str = "TestObj", poly_count: int = 12):
        self.name = name
        self.type = "MESH"
        self.data = MockMesh(poly_count)
        self.matrix_world = MagicMock()


# ==============================================================================
# 1. PCA Splitting Plane Tests
# ==============================================================================


def test_pca_splitting_plane_empty_coords():
    centroid, normal = CollisionDecomposer.compute_pca_splitting_plane(np.empty((0, 3)))
    assert centroid.x == 0.0 and centroid.y == 0.0 and centroid.z == 0.0
    assert normal.x == 0.0 and normal.y == 0.0 and normal.z == 1.0


def test_pca_splitting_plane_single_coord():
    coords = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)
    centroid, normal = CollisionDecomposer.compute_pca_splitting_plane(coords)
    assert pytest.approx(centroid.x) == 1.0
    assert pytest.approx(centroid.y) == 2.0
    assert pytest.approx(centroid.z) == 3.0
    assert normal.x == 0.0 and normal.y == 0.0 and normal.z == 1.0


def test_pca_splitting_plane_two_coords():
    coords = np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=np.float32)
    centroid, normal = CollisionDecomposer.compute_pca_splitting_plane(coords)
    assert pytest.approx(centroid.x) == 1.0
    assert normal.z == 1.0


def test_pca_splitting_plane_cube_points():
    coords = np.array(
        [
            [-1.0, -1.0, -1.0],
            [1.0, -1.0, -1.0],
            [-1.0, 1.0, -1.0],
            [1.0, 1.0, -1.0],
            [-1.0, -1.0, 1.0],
            [1.0, -1.0, 1.0],
            [-1.0, 1.0, 1.0],
            [1.0, 1.0, 1.0],
        ],
        dtype=np.float32,
    )
    centroid, normal = CollisionDecomposer.compute_pca_splitting_plane(coords)
    assert pytest.approx(centroid.length) == 0.0
    assert pytest.approx(normal.length) == 1.0


def test_pca_splitting_plane_svd_fallback():
    coords = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
    with patch("numpy.linalg.svd", side_effect=np.linalg.LinAlgError("SVD did not converge")):
        centroid, normal = CollisionDecomposer.compute_pca_splitting_plane(coords)
        assert pytest.approx(centroid.x) == 1.0 / 3.0
        assert normal.x == 0.0 and normal.y == 0.0 and normal.z == 1.0


# ==============================================================================
# 2. Hull Concavity Measurement Tests
# ==============================================================================


def test_measure_hull_concavity_none_inputs():
    assert CollisionDecomposer.measure_hull_concavity(None, None) == 0.0
    bm = MockBMesh()
    assert CollisionDecomposer.measure_hull_concavity(None, bm) == 0.0  # type: ignore[arg-type]
    assert CollisionDecomposer.measure_hull_concavity(bm, None) == 0.0  # type: ignore[arg-type]


def test_measure_hull_concavity_empty_faces():
    bm_empty = MockBMesh(vert_count=0, face_count=0)
    bm_full = MockBMesh(vert_count=4, face_count=4)
    assert CollisionDecomposer.measure_hull_concavity(bm_empty, bm_full) == 0.0  # type: ignore[arg-type]
    assert CollisionDecomposer.measure_hull_concavity(bm_full, bm_empty) == 0.0  # type: ignore[arg-type]


def test_measure_hull_concavity_with_mock_bvh():
    bm_src = MockBMesh(vert_count=8, face_count=6)
    bm_hull = MockBMesh(vert_count=8, face_count=6)
    with patch("core.collision_decomposer.BVHTree", MockBVHTree):
        dist = CollisionDecomposer.measure_hull_concavity(bm_src, bm_hull)  # type: ignore[arg-type]
        assert pytest.approx(dist) == 0.05


def test_measure_hull_concavity_stratified_sampling_large_mesh():
    bm_large = MockBMesh(vert_count=600, face_count=600)
    bm_hull = MockBMesh(vert_count=8, face_count=6)
    with patch("core.collision_decomposer.BVHTree", MockBVHTree):
        dist = CollisionDecomposer.measure_hull_concavity(bm_large, bm_hull)  # type: ignore[arg-type]
        assert pytest.approx(dist) == 0.05


def test_measure_hull_concavity_bvh_tree_none():
    bm_src = MockBMesh()
    bm_hull = MockBMesh()
    mock_tree_none = MagicMock()
    mock_tree_none.FromBMesh.return_value = None
    with patch("core.collision_decomposer.BVHTree", mock_tree_none):
        assert CollisionDecomposer.measure_hull_concavity(bm_src, bm_hull) == 0.0  # type: ignore[arg-type]


# ==============================================================================
# 3. Hull Hardening Tests
# ==============================================================================


def test_harden_convex_hull_none_input():
    assert CollisionDecomposer.harden_convex_hull(None) is False


def test_harden_convex_hull_too_few_verts():
    bm = MockBMesh(vert_count=2, face_count=0)
    assert CollisionDecomposer.harden_convex_hull(bm) is False  # type: ignore[arg-type]


def test_harden_convex_hull_success_mocked_bmesh_ops():
    bm = MockBMesh(vert_count=8, face_count=6)
    mock_bmesh = MagicMock()
    mock_bmesh.ops.convex_hull.return_value = {"geom": []}
    with patch("core.collision_decomposer.bmesh", mock_bmesh):
        result = CollisionDecomposer.harden_convex_hull(bm, max_verts=32)  # type: ignore[arg-type]
        assert result is True


def test_harden_convex_hull_planar_extrusion():
    bm = MockBMesh(vert_count=4, face_count=1)
    for v in bm.verts:
        v.co = Vector((1.0, 1.0, 0.0))
    mock_bmesh = MagicMock()
    mock_bmesh.types.BMVert = MockBMVert
    mock_bmesh.ops.extrude_face_region.return_value = {"geom": [MockBMVert()]}
    mock_bmesh.ops.convex_hull.return_value = {"geom": []}
    with patch("core.collision_decomposer.bmesh", mock_bmesh):
        result = CollisionDecomposer.harden_convex_hull(bm, min_thickness=0.05)  # type: ignore[arg-type]
        assert result is True


# ==============================================================================
# 4. Hull Vertex Budget Clamping Tests
# ==============================================================================


def test_clamp_hull_vertex_budget_already_within_budget():
    bm = MockBMesh(vert_count=16, face_count=12)
    mock_bmesh = MagicMock()
    with patch("core.collision_decomposer.bmesh", mock_bmesh):
        CollisionDecomposer._clamp_hull_vertex_budget(bm, max_verts=32)  # type: ignore[arg-type]
        mock_bmesh.ops.decimate.assert_not_called()


def test_clamp_hull_vertex_budget_exceeds_budget():
    bm = MockBMesh(vert_count=48, face_count=24)
    mock_bmesh = MagicMock()
    mock_bmesh.ops.convex_hull.return_value = {"geom": []}
    with patch("core.collision_decomposer.bmesh", mock_bmesh):
        CollisionDecomposer._clamp_hull_vertex_budget(bm, max_verts=32)  # type: ignore[arg-type]
        mock_bmesh.ops.dissolve_limit.assert_called_once()
        assert mock_bmesh.ops.collapse.called


# ==============================================================================
# 5. Multi-Convex Decomposition Tests
# ==============================================================================


def test_decompose_mesh_invalid_target_obj():
    assert CollisionDecomposer.decompose_mesh_to_hulls(None) == []

    non_mesh = MockObject("Armature")
    non_mesh.type = "ARMATURE"
    assert CollisionDecomposer.decompose_mesh_to_hulls(non_mesh) == []  # type: ignore[arg-type]


def test_decompose_mesh_empty_geometry():
    empty_obj = MockObject("EmptyMesh", poly_count=0)
    assert CollisionDecomposer.decompose_mesh_to_hulls(empty_obj) == []  # type: ignore[arg-type]


def test_decompose_mesh_single_convex_hull():
    obj = MockObject("Box", poly_count=6)
    fake_bm = MockBMesh(vert_count=8, face_count=6)
    mock_bmesh = MagicMock()
    mock_bmesh.new.return_value = fake_bm

    with (
        patch("core.collision_decomposer.bmesh", mock_bmesh),
        patch.object(CollisionDecomposer, "measure_hull_concavity", return_value=0.01),
        patch.object(CollisionDecomposer, "harden_convex_hull", return_value=True),
    ):
        res = CollisionDecomposer.decompose_mesh_to_hulls(
            obj,  # type: ignore[arg-type]
            k_target=1,
            concavity_threshold=0.05,
        )
        assert len(res) == 1
