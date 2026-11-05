"""
Deep unit tests for core/chunking.py.
Tests SpatialGridSpec generation, boundary cutting plane computation,
cell index bucket resolution, adaptive quadtree cell clustering,
and MeshChunkSlicer initialization guards.
"""

from __future__ import annotations

from typing import Any

from unittest.mock import MagicMock, patch

from core.chunking import (
    AdaptiveCellClusterer,
    MeshChunkSlicer,
    SpatialGridSpec,
)
from core.compat import Matrix, Vector


class MockBoundBoxObject:
    def __init__(
        self,
        name: str = "TerrainMesh",
        bound_box: list[tuple[float, float, float]] | None = None,
        matrix_world: Any = None,
    ):
        self.name = name
        self.type = "MESH"
        self.data: Any = MagicMock(name=f"{name}_Mesh", vertices=[])
        self.bound_box = bound_box or [
            (-10.0, -10.0, 0.0),
            (10.0, -10.0, 0.0),
            (10.0, 10.0, 0.0),
            (-10.0, 10.0, 0.0),
            (-10.0, -10.0, 5.0),
            (10.0, -10.0, 5.0),
            (10.0, 10.0, 5.0),
            (-10.0, 10.0, 5.0),
        ]
        self.matrix_world = matrix_world or (Matrix.Identity(4) if Matrix else MagicMock())


class MockBlendData:
    def __init__(self):
        self.objects = MagicMock()
        self.meshes = MagicMock()


# ==============================================================================
# SpatialGridSpec Tests
# ==============================================================================


def test_spatial_grid_spec_from_null_or_empty_object():
    # None object
    spec_none = SpatialGridSpec.from_object(None)
    assert spec_none.num_cells_x == 1
    assert spec_none.num_cells_y == 1

    # Object without bound_box
    empty_obj = MockBoundBoxObject()
    empty_obj.bound_box = []
    spec_empty = SpatialGridSpec.from_object(empty_obj)  # type: ignore[arg-type]
    assert spec_empty.num_cells_x == 1


def test_spatial_grid_spec_cutting_planes_2d():
    # Box from (-20, -20, 0) to (20, 20, 10) with cell size 10 -> 4 cells each axis
    bound_box = [
        (-20.0, -20.0, 0.0),
        (20.0, -20.0, 0.0),
        (20.0, 20.0, 0.0),
        (-20.0, 20.0, 0.0),
        (-20.0, -20.0, 10.0),
        (20.0, -20.0, 10.0),
        (20.0, 20.0, 10.0),
        (-20.0, 20.0, 10.0),
    ]
    obj = MockBoundBoxObject(bound_box=bound_box)
    spec = SpatialGridSpec.from_object(
        obj,  # type: ignore[arg-type]
        cell_size_meters=10.0,
        split_z=False,  # type: ignore[arg-type]
    )

    assert spec.num_cells_x == 4
    assert spec.num_cells_y == 4
    assert spec.num_cells_z == 1
    assert len(spec.x_cut_planes) == 3
    assert len(spec.y_cut_planes) == 3
    assert len(spec.z_cut_planes) == 0

    # Cut planes should be spaced at -10, 0, 10
    assert abs(spec.x_cut_planes[0] - (-10.0)) < 1e-4
    assert abs(spec.x_cut_planes[1] - 0.0) < 1e-4
    assert abs(spec.x_cut_planes[2] - 10.0) < 1e-4


def test_spatial_grid_spec_cutting_planes_3d_split_z():
    bound_box = [
        (0.0, 0.0, 0.0),
        (10.0, 0.0, 0.0),
        (10.0, 10.0, 0.0),
        (0.0, 10.0, 0.0),
        (0.0, 0.0, 30.0),
        (10.0, 0.0, 30.0),
        (10.0, 10.0, 30.0),
        (0.0, 10.0, 30.0),
    ]
    obj = MockBoundBoxObject(bound_box=bound_box)
    spec = SpatialGridSpec.from_object(
        obj,  # type: ignore[arg-type]
        cell_size_meters=10.0,
        split_z=True,
        z_cell_size=10.0,  # type: ignore[arg-type]
    )

    assert spec.num_cells_x == 1
    assert spec.num_cells_y == 1
    assert spec.num_cells_z == 3
    assert len(spec.z_cut_planes) == 2
    assert abs(spec.z_cut_planes[0] - 10.0) < 1e-4
    assert abs(spec.z_cut_planes[1] - 20.0) < 1e-4


def test_spatial_grid_spec_get_cell_index_clamping():
    spec = SpatialGridSpec(
        min_corner=(0.0, 0.0, 0.0),
        max_corner=(100.0, 100.0, 50.0),
        cell_size_x=25.0,
        cell_size_y=25.0,
        cell_size_z=25.0,
        num_cells_x=4,
        num_cells_y=4,
        num_cells_z=2,
        split_z=True,
    )

    # Point inside cell (1, 2, 0)
    ix, iy, iz = spec.get_cell_index((30.0, 60.0, 10.0))
    assert (ix, iy, iz) == (1, 2, 0)

    # Point far outside should clamp to min / max cell
    ix_neg, iy_neg, iz_neg = spec.get_cell_index((-50.0, -100.0, -20.0))
    assert (ix_neg, iy_neg, iz_neg) == (0, 0, 0)

    ix_max, iy_max, iz_max = spec.get_cell_index((500.0, 500.0, 500.0))
    assert (ix_max, iy_max, iz_max) == (3, 3, 1)


def test_spatial_grid_spec_parent_cluster_index():
    spec = SpatialGridSpec(split_z=False)
    # Stride 2 quadtree
    assert spec.get_parent_cluster_index(3, 2, 0, stride=2) == (1, 1, 0)
    assert spec.get_parent_cluster_index(0, 1, 0, stride=2) == (0, 0, 0)

    # 3D with split_z
    spec_3d = SpatialGridSpec(split_z=True)
    assert spec_3d.get_parent_cluster_index(4, 5, 6, stride=2) == (2, 2, 3)


# ==============================================================================
# AdaptiveCellClusterer Tests
# ==============================================================================


def test_adaptive_clusterer_empty_buckets():
    spec = SpatialGridSpec()
    assert AdaptiveCellClusterer.cluster_cells({}, spec) == {}


def test_adaptive_clusterer_groups_under_budget():
    spec = SpatialGridSpec(num_cells_x=2, num_cells_y=2, split_z=False)
    # 4 cells each with 10 faces -> total 40 faces. Budget = 100
    buckets = {
        (0, 0, 0): list(range(10)),
        (1, 0, 0): list(range(10, 20)),
        (0, 1, 0): list(range(20, 30)),
        (1, 1, 0): list(range(30, 40)),
    }

    clustered = AdaptiveCellClusterer.cluster_cells(buckets, spec, target_polys_per_cluster=100)

    # All 4 cells should be grouped into a single cluster
    assert len(clustered) == 1
    assert "Cluster_X0-1_Y0-1" in clustered
    assert len(clustered["Cluster_X0-1_Y0-1"]) == 40


def test_adaptive_clusterer_splits_when_over_budget():
    spec = SpatialGridSpec(num_cells_x=2, num_cells_y=2, split_z=False)
    # 4 cells each with 50 faces -> total 200 faces. Budget = 80
    buckets = {
        (0, 0, 0): list(range(50)),
        (1, 0, 0): list(range(50, 100)),
        (0, 1, 0): list(range(100, 150)),
        (1, 1, 0): list(range(150, 200)),
    }

    clustered = AdaptiveCellClusterer.cluster_cells(buckets, spec, target_polys_per_cluster=80)

    # Cells should remain individual chunks because the combined block exceeds budget
    assert len(clustered) == 4
    assert "Chunk_X0_Y0" in clustered
    assert "Chunk_X1_Y0" in clustered
    assert "Chunk_X0_Y1" in clustered
    assert "Chunk_X1_Y1" in clustered


def test_adaptive_clusterer_with_z_split():
    spec = SpatialGridSpec(num_cells_x=2, num_cells_y=2, num_cells_z=2, split_z=True)
    buckets = {
        (0, 0, 0): [1, 2],
        (1, 0, 0): [3, 4],
        (0, 0, 1): [5, 6],
    }

    clustered = AdaptiveCellClusterer.cluster_cells(buckets, spec, target_polys_per_cluster=100)

    # Z=0 has 2 cells grouped into cluster
    assert "Cluster_X0-1_Y0-1_Z0" in clustered
    # Z=1 has 1 cell left as individual chunk
    assert "Cluster_X0-1_Y0-1_Z1" in clustered


# ==============================================================================
# MeshChunkSlicer Initialization Guards
# ==============================================================================


def test_mesh_chunk_slicer_null_guards():
    bdata = MockBlendData()
    spec = SpatialGridSpec()

    # None object
    res_none = MeshChunkSlicer.slice_and_partition(
        None,
        spec,
        "Chunk",
        None,
        blend_data=bdata,  # type: ignore[arg-type]
    )
    assert res_none == []

    # Non-mesh object
    arm_obj = MockBoundBoxObject()
    arm_obj.type = "ARMATURE"
    res_arm = MeshChunkSlicer.slice_and_partition(
        arm_obj,  # type: ignore[arg-type]
        spec,
        "Chunk",
        None,
        blend_data=bdata,  # type: ignore[arg-type]
    )
    assert res_arm == []


def test_mesh_chunk_slicer_empty_mesh_guards():
    bdata = MockBlendData()
    spec = SpatialGridSpec()
    obj = MockBoundBoxObject()

    mock_bpy = MagicMock()
    mock_bmesh = MagicMock()

    class MockVec:
        def __init__(self, co):
            self.x, self.y, self.z = co[0], co[1], co[2]

        def normalized(self):
            return self

        def __iter__(self):
            return iter((self.x, self.y, self.z))

        def __getitem__(self, i):
            return (self.x, self.y, self.z)[i]

    with (
        patch("core.chunking.bpy", mock_bpy),
        patch("core.chunking.Vector", MockVec),
        patch("core.chunking.bmesh", mock_bmesh),
        patch("core.chunking.ModifierManager.get_evaluated_mesh", return_value=(None, None)),
    ):
        res = MeshChunkSlicer.slice_and_partition(
            obj,  # type: ignore[arg-type]
            spec,
            "Chunk",
            None,
            blend_data=bdata,  # type: ignore[arg-type]
        )
        assert res == []


def test_recenter_pivot_stationary_chunk_slicer():
    class MockVertex:
        def __init__(self, x: float, y: float, z: float):
            self.co = Vector((x, y, z)) if Vector else MagicMock(x=x, y=y, z=z)

    # Empty and non-mesh guards
    MeshChunkSlicer._recenter_pivot_stationary(None)
    arm = MockBoundBoxObject()
    arm.type = "ARMATURE"
    MeshChunkSlicer._recenter_pivot_stationary(arm)  # type: ignore[arg-type]

    # Empty vertices
    empty = MockBoundBoxObject()
    empty.data = MagicMock(vertices=[])
    MeshChunkSlicer._recenter_pivot_stationary(empty)  # type: ignore[arg-type]

    # Already centered
    centered = MockBoundBoxObject()
    centered.data = MagicMock(vertices=[MockVertex(-1, 0, 0), MockVertex(1, 0, 0)])
    MeshChunkSlicer._recenter_pivot_stationary(centered)  # type: ignore[arg-type]
    assert abs(centered.data.vertices[0].co.x - (-1.0)) < 1e-4

    # Offset vertices
    offset = MockBoundBoxObject()
    v1 = MockVertex(10, 0, 0)
    v2 = MockVertex(20, 0, 0)
    offset.data = MagicMock(vertices=[v1, v2])
    offset.matrix_world = Matrix.Identity(4) if Matrix else MagicMock()
    MeshChunkSlicer._recenter_pivot_stationary(offset)  # type: ignore[arg-type]
    assert abs(v1.co.x - (-5.0)) < 1e-4
    assert abs(v2.co.x - 5.0) < 1e-4


def test_mesh_chunk_slicer_execution_flow():
    bdata = MockBlendData()
    spec = SpatialGridSpec(
        min_corner=(-10, -10, 0),
        max_corner=(10, 10, 10),
        num_cells_x=2,
        num_cells_y=2,
        x_cut_planes=[0.0],
        y_cut_planes=[0.0],
        split_z=False,
    )
    source_obj = MockBoundBoxObject()
    mock_mat = MagicMock()
    mock_mat.inverted.return_value = mock_mat
    mock_mat.to_3x3.return_value.transposed.return_value = mock_mat
    mock_mat.__matmul__.return_value = Vector((0.0, 0.0, 0.0)) if Vector else MagicMock()
    source_obj.matrix_world = mock_mat

    mock_eval_mesh = MagicMock(polygons=[MagicMock()])
    mock_eval_obj = MagicMock()

    mock_bmesh = MagicMock()
    mock_bm = MagicMock()
    mock_face = MagicMock(index=0)
    mock_face.calc_center_median.return_value = (0.0, 0.0, 0.0)
    mock_bm.faces = MagicMock()
    mock_bm.faces.__iter__.return_value = [mock_face]
    mock_bm.faces.__getitem__.return_value = [mock_face]
    mock_bm.edges = MagicMock()
    mock_bm.edges.__getitem__.return_value = []
    mock_bm.verts = MagicMock()
    mock_bm.verts.__getitem__.return_value = []
    mock_bmesh.new.return_value = mock_bm

    mock_bpy = MagicMock()

    class MockVec:
        def __init__(self, co):
            self.x, self.y, self.z = co[0], co[1], co[2]

        def normalized(self):
            return self

        def __iter__(self):
            return iter((self.x, self.y, self.z))

        def __getitem__(self, i):
            return (self.x, self.y, self.z)[i]

    with (
        patch("core.chunking.bpy", mock_bpy),
        patch("core.chunking.Vector", MockVec),
        patch("core.chunking.bmesh", mock_bmesh),
        patch("core.chunking.ModifierManager.get_evaluated_mesh", return_value=(mock_eval_mesh, mock_eval_obj)),
        patch.object(
            MeshChunkSlicer, "_extract_single_chunk", return_value=MagicMock(name="ExtractedChunk")
        ) as mock_extract,
    ):
        res = MeshChunkSlicer.slice_and_partition(
            source_obj=source_obj,  # type: ignore[arg-type]
            grid_spec=spec,
            base_name="Terrain",
            target_collection=None,
            partitioning_mode="ADAPTIVE_CLUSTERING",
            blend_data=bdata,  # type: ignore[arg-type]
        )

        assert len(res) >= 1
        assert mock_extract.called
        assert mock_bm.free.called
        assert mock_eval_obj.to_mesh_clear.called
