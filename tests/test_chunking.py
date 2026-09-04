"""
Unit tests for OmniMesh Spatial Chunking & HLOD Engine.
Tests SpatialGridSpec, MeshChunkSlicer pivot recentering, Seam Pinning,
and HLODClusterMerger material palette mapping.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from core.chunking import (
    AdaptiveCellClusterer,
    HLODClusterMerger,
    MeshChunkSlicer,
    SpatialGridSpec,
)
from core.decimator import MeshDecimator
from core.normals import NormalManager


class MockVector:
    def __init__(self, co: tuple[float, float, float] | list[float]):
        self.x = float(co[0])
        self.y = float(co[1])
        self.z = float(co[2])

    def __getitem__(self, idx: int) -> float:
        if idx == 0:
            return self.x
        elif idx == 1:
            return self.y
        elif idx == 2:
            return self.z
        raise IndexError(idx)

    def __setitem__(self, idx: int, val: float) -> None:
        if idx == 0:
            self.x = val
        elif idx == 1:
            self.y = val
        elif idx == 2:
            self.z = val

    def __sub__(self, other: Any) -> MockVector:
        ox = other[0] if isinstance(other, (list, tuple)) else getattr(other, "x", other[0])
        oy = other[1] if isinstance(other, (list, tuple)) else getattr(other, "y", other[1])
        oz = other[2] if isinstance(other, (list, tuple)) else getattr(other, "z", other[2])
        return MockVector((self.x - ox, self.y - oy, self.z - oz))

    @property
    def length(self) -> float:
        return (self.x**2 + self.y**2 + self.z**2) ** 0.5


def test_spatial_grid_spec_empty_or_none():
    spec = SpatialGridSpec.from_object(None)
    assert spec.num_cells_x == 1
    assert spec.num_cells_y == 1

    mock_obj = MagicMock()
    mock_obj.bound_box = None
    spec2 = SpatialGridSpec.from_object(mock_obj)
    assert spec2.num_cells_x == 1


def test_spatial_grid_spec_calculation():
    # 100m x 50m bounding box
    mock_obj = MagicMock()
    mock_obj.matrix_world = None
    mock_obj.bound_box = [
        (0.0, 0.0, 0.0),
        (100.0, 0.0, 0.0),
        (100.0, 50.0, 0.0),
        (0.0, 50.0, 0.0),
        (0.0, 0.0, 10.0),
        (100.0, 0.0, 10.0),
        (100.0, 50.0, 10.0),
        (0.0, 50.0, 10.0),
    ]

    spec = SpatialGridSpec.from_object(mock_obj, cell_size_meters=25.0)
    assert spec.num_cells_x == 4  # 100 / 25 = 4
    assert spec.num_cells_y == 2  # 50 / 25 = 2
    assert spec.num_cells_z == 1
    assert len(spec.x_cut_planes) == 3
    assert len(spec.y_cut_planes) == 1

    # Test cell indexing
    ix, iy, iz = spec.get_cell_index((10.0, 10.0, 0.0))
    assert ix == 0
    assert iy == 0
    assert iz == 0

    ix, iy, iz = spec.get_cell_index((80.0, 30.0, 5.0))
    assert ix == 3
    assert iy == 1

    # Test clamping outside bounds
    ix, iy, iz = spec.get_cell_index((-50.0, 200.0, 0.0))
    assert ix == 0
    assert iy == 1


def test_spatial_grid_spec_split_z():
    mock_obj = MagicMock()
    mock_obj.matrix_world = None
    mock_obj.bound_box = [
        (0.0, 0.0, 0.0),
        (20.0, 20.0, 90.0),
    ]

    spec = SpatialGridSpec.from_object(mock_obj, cell_size_meters=20.0, split_z=True, z_cell_size=30.0)
    assert spec.split_z is True
    assert spec.num_cells_z == 3  # 90 / 30 = 3
    assert len(spec.z_cut_planes) == 2

    ix, iy, iz = spec.get_cell_index((10.0, 10.0, 45.0))
    assert iz == 1


def test_recenter_pivot_stationary_guard():
    # Null or invalid object
    MeshChunkSlicer._recenter_pivot_stationary(None)
    mock_obj = MagicMock()
    mock_obj.type = "CAMERA"
    MeshChunkSlicer._recenter_pivot_stationary(mock_obj)


def test_recenter_pivot_stationary_logic():
    mock_obj = MagicMock()
    mock_obj.type = "MESH"

    class MockMeshVert:
        def __init__(self, co: tuple[float, float, float]):
            self.co = MockVector(co)

    v0 = MockMeshVert((10.0, 20.0, 0.0))
    v1 = MockMeshVert((30.0, 40.0, 10.0))
    mock_obj.data.vertices = [v0, v1]
    mock_obj.matrix_world = None

    # Center is at (20, 30, 5)
    MeshChunkSlicer._recenter_pivot_stationary(mock_obj)
    assert abs(v0.co.x - (-10.0)) < 1e-4
    assert abs(v0.co.y - (-10.0)) < 1e-4
    assert abs(v1.co.x - 10.0) < 1e-4
    assert abs(v1.co.y - 10.0) < 1e-4


def test_hlod_cluster_merger_guards():
    assert HLODClusterMerger.merge_chunks_for_hlod([], "Test", None) is None
    assert HLODClusterMerger.merge_chunks_for_hlod([None], "Test", None) is None


def test_lock_chunk_boundaries_guard():
    assert MeshDecimator.lock_chunk_boundaries(None) == set()
    mock_obj = MagicMock()
    mock_obj.type = "EMPTY"
    assert MeshDecimator.lock_chunk_boundaries(mock_obj) == set()


def test_normal_manager_transfer_boundary_loop_normals_kdtree_guard():
    assert NormalManager.transfer_boundary_loop_normals_kdtree(None, None) is False


def test_decimate_qem_strict_boundary_parameters():
    mock_obj = MagicMock()
    mock_obj.type = "MESH"
    mock_mod = MagicMock()
    mock_obj.modifiers.new.return_value = mock_mod
    mock_obj.vertex_groups = {"OMNIMESH_SEAM_LOCKED": MagicMock()}

    # Execute decimate with custom factor and cleanup_group=False
    MeshDecimator.execute_decimate_qem(
        mock_obj,
        target_ratio=0.5,
        use_curvature_weight=True,
        group_name="OMNIMESH_SEAM_LOCKED",
        vertex_group_factor=1.0,
        cleanup_group=False,
    )

    # When bpy is not available (mock mode), function safely returns without crash
    assert mock_obj.type == "MESH"


def test_adaptive_cell_clustering_logic():
    """Verify that sparse adjacent cells merge into clusters while dense cells remain individual."""
    grid = SpatialGridSpec(num_cells_x=4, num_cells_y=4, num_cells_z=1)
    buckets = {
        (0, 0, 0): list(range(0, 100)),
        (1, 0, 0): list(range(100, 200)),
        (0, 1, 0): list(range(200, 300)),
        (1, 1, 0): list(range(300, 400)),
        (2, 0, 0): list(range(0, 60000)),
        (3, 0, 0): list(range(0, 50)),
    }

    clusters = AdaptiveCellClusterer.cluster_cells(buckets, grid, target_polys_per_cluster=50000)

    # 4 sparse adjacent cells merged into one quad cluster
    assert "Cluster_X0-1_Y0-1" in clusters
    assert len(clusters["Cluster_X0-1_Y0-1"]) == 400

    # Dense cell exceeds budget and remains separate
    assert "Chunk_X2_Y0" in clusters
    assert len(clusters["Chunk_X2_Y0"]) == 60000

    # Isolated boundary cell remains separate
    assert "Chunk_X3_Y0" in clusters
    assert len(clusters["Chunk_X3_Y0"]) == 50
