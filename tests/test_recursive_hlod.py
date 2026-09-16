"""
Unit tests for OmniMesh Recursive Quadtree/Octree HLOD Manager.
Tests spatial downsampling, coordinate extraction, non-power-of-two (odd) grid handling,
and stationary pivot recentering across hierarchical tiers.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from core.chunking import SpatialGridSpec
from core.recursive_hlod import RecursiveHLODManager


def test_quadtree_spatial_coordinate_extraction():
    # 1. Custom property extraction
    mock_obj = MagicMock()
    mock_obj.name = "CustomChunk"
    mock_obj.get.side_effect = lambda k, d=None: 3 if k == "_chunk_ix" else (2 if k == "_chunk_iy" else d)
    mock_obj.__contains__ = lambda self, k: k in ("_chunk_ix", "_chunk_iy")

    coords = RecursiveHLODManager.extract_cell_coordinates(mock_obj)
    assert coords == (3, 2, 0)

    # 2. Regex extraction from standard name Chunk_X1_Y3
    mock_named = MagicMock()
    mock_named.name = "SM_Building_Chunk_X1_Y3"
    mock_named.get.side_effect = lambda k, d=None: d
    mock_named.__contains__ = lambda self, k: False
    coords2 = RecursiveHLODManager.extract_cell_coordinates(mock_named)
    assert coords2 == (1, 3, 0)

    # 3. Regex extraction with Z axis
    mock_z = MagicMock()
    mock_z.name = "SM_Building_Chunk_X2_Y0_Z4"
    mock_z.get.side_effect = lambda k, d=None: d
    mock_z.__contains__ = lambda self, k: False
    coords3 = RecursiveHLODManager.extract_cell_coordinates(mock_z)
    assert coords3 == (2, 0, 4)


def test_quadtree_parent_cluster_downsampling_math():
    grid = SpatialGridSpec(num_cells_x=8, num_cells_y=8, num_cells_z=1)

    # Level 1: Stride 2 (4x4 clusters)
    p0 = grid.get_parent_cluster_index(0, 0, stride=2)
    p1 = grid.get_parent_cluster_index(1, 1, stride=2)
    p2 = grid.get_parent_cluster_index(2, 3, stride=2)
    p3 = grid.get_parent_cluster_index(7, 7, stride=2)

    assert p0 == (0, 0, 0)
    assert p1 == (0, 0, 0)
    assert p2 == (1, 1, 0)
    assert p3 == (3, 3, 0)

    # Level 2: Stride 4 (2x2 clusters)
    assert grid.get_parent_cluster_index(0, 0, stride=4) == (0, 0, 0)
    assert grid.get_parent_cluster_index(3, 3, stride=4) == (0, 0, 0)
    assert grid.get_parent_cluster_index(4, 4, stride=4) == (1, 1, 0)
    assert grid.get_parent_cluster_index(7, 7, stride=4) == (1, 1, 0)


def test_group_chunks_quadtree_odd_3x3_grid():
    """
    Verifies that a 3x3 grid (9 chunks) groups cleanly into:
    (0,0): 4 chunks, (0,1): 2 chunks, (1,0): 2 chunks, (1,1): 1 chunk.
    Zero dropped chunks or out-of-bound errors.
    """
    grid = SpatialGridSpec(num_cells_x=3, num_cells_y=3, num_cells_z=1)

    chunks = []
    for ix in range(3):
        for iy in range(3):
            obj = MagicMock()
            obj.type = "MESH"
            obj.name = f"City_Chunk_X{ix}_Y{iy}"
            obj.get.side_effect = lambda k, d=None: d
            obj.__contains__ = lambda self, k: False
            chunks.append(obj)

    assert len(chunks) == 9

    clusters = RecursiveHLODManager.group_chunks_quadtree(chunks, grid_spec=grid, stride=2)

    assert (0, 0, 0) in clusters
    assert len(clusters[(0, 0, 0)]) == 4  # (0,0), (0,1), (1,0), (1,1)

    assert (0, 1, 0) in clusters
    assert len(clusters[(0, 1, 0)]) == 2  # (0,2), (1,2)

    assert (1, 0, 0) in clusters
    assert len(clusters[(1, 0, 0)]) == 2  # (2,0), (2,1)

    assert (1, 1, 0) in clusters
    assert len(clusters[(1, 1, 0)]) == 1  # (2,2) - corner single chunk

    # Total grouped objects must match input exactly
    total_assigned = sum(len(objs) for objs in clusters.values())
    assert total_assigned == 9


def test_build_hierarchical_tier_guards():
    # Null or empty cluster dictionary returns empty list safely
    assert RecursiveHLODManager.build_hierarchical_tier({}, "SM_Test", 2, None) == []
    assert RecursiveHLODManager.build_hierarchical_tier({(0, 0, 0): []}, "SM_Test", 2, None) == []


def test_apply_voxel_proxy_shell_guards():
    # Null or invalid object
    assert RecursiveHLODManager.apply_voxel_proxy_shell(None) is False

    mock_empty = MagicMock()
    mock_empty.type = "EMPTY"
    assert RecursiveHLODManager.apply_voxel_proxy_shell(mock_empty) is False


def test_multitier_recursive_quadtree_reduction():
    """
    Verifies that multi-tier recursive reduction downsamples cleanly:
    LOD1 (8x8 = 64 chunks) -> LOD2 (4x4 = 16 clusters) -> LOD3 (2x2 = 4 clusters) -> LOD4 (1x1 = 1 cluster)
    Ensures zero over-stride bug or premature collapse.
    """
    grid = SpatialGridSpec(num_cells_x=8, num_cells_y=8, num_cells_z=1)

    # Initial 8x8 = 64 chunks
    current_tier_objs = []
    for ix in range(8):
        for iy in range(8):
            obj = MagicMock()
            obj.type = "MESH"
            obj.name = f"City_Chunk_X{ix}_Y{iy}"
            obj.get.side_effect = lambda k, d=None, x=ix, y=iy: (
                x if k == "_chunk_ix" else (y if k == "_chunk_iy" else d)
            )
            obj.__contains__ = lambda self, k: k in ("_chunk_ix", "_chunk_iy")
            current_tier_objs.append(obj)

    assert len(current_tier_objs) == 64

    # Step 1: LOD1 (8x8) -> LOD2 (4x4 = 16 clusters) with normalized stride 2
    clusters_lod2 = RecursiveHLODManager.group_chunks_quadtree(current_tier_objs, grid_spec=grid, stride=2)
    assert len(clusters_lod2) == 16
    for (cx, cy, _), members in clusters_lod2.items():
        assert len(members) == 4
        assert 0 <= cx < 4
        assert 0 <= cy < 4

    # Simulate LOD2 objects stamped with downsampled coordinates
    lod2_objs = []
    for cx, cy, cz in clusters_lod2.keys():
        obj = MagicMock()
        obj.type = "MESH"
        obj.name = f"City_HLOD_LOD2_X{cx}_Y{cy}"
        obj.get.side_effect = lambda k, d=None, x=cx, y=cy, z=cz: (
            x if k == "_chunk_ix" else (y if k == "_chunk_iy" else (z if k == "_chunk_iz" else d))
        )
        obj.__contains__ = lambda self, k: k in ("_chunk_ix", "_chunk_iy", "_chunk_iz")
        lod2_objs.append(obj)

    assert len(lod2_objs) == 16

    # Step 2: LOD2 (4x4) -> LOD3 (2x2 = 4 clusters) with normalized stride 2
    clusters_lod3 = RecursiveHLODManager.group_chunks_quadtree(lod2_objs, grid_spec=grid, stride=2)
    assert len(clusters_lod3) == 4
    for (cx, cy, _), members in clusters_lod3.items():
        assert len(members) == 4
        assert 0 <= cx < 2
        assert 0 <= cy < 2

    # Simulate LOD3 objects
    lod3_objs = []
    for cx, cy, cz in clusters_lod3.keys():
        obj = MagicMock()
        obj.type = "MESH"
        obj.name = f"City_HLOD_LOD3_X{cx}_Y{cy}"
        obj.get.side_effect = lambda k, d=None, x=cx, y=cy, z=cz: (
            x if k == "_chunk_ix" else (y if k == "_chunk_iy" else (z if k == "_chunk_iz" else d))
        )
        obj.__contains__ = lambda self, k: k in ("_chunk_ix", "_chunk_iy", "_chunk_iz")
        lod3_objs.append(obj)

    assert len(lod3_objs) == 4

    # Step 3: LOD3 (2x2) -> LOD4 (1x1 = 1 cluster) with normalized stride 2
    clusters_lod4 = RecursiveHLODManager.group_chunks_quadtree(lod3_objs, grid_spec=grid, stride=2)
    assert len(clusters_lod4) == 1
    assert (0, 0, 0) in clusters_lod4
    assert len(clusters_lod4[(0, 0, 0)]) == 4
