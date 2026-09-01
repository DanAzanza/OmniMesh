"""
Unit tests for OmniMesh Multi-Convex Collision Hull Generator & Physics Decomposition Engine.
"""

from __future__ import annotations

import math
import numpy as np

from core.collision import CollisionDecomposer, CollisionManager


def test_pca_splitting_plane_basic():
    # Coords forming a symmetric 3D rectangular box elongated along X axis
    coords = np.array(
        [
            [-5.0, -1.0, -1.0],
            [5.0, -1.0, -1.0],
            [-5.0, 1.0, -1.0],
            [5.0, 1.0, -1.0],
            [-5.0, -1.0, 1.0],
            [5.0, -1.0, 1.0],
            [-5.0, 1.0, 1.0],
            [5.0, 1.0, 1.0],
        ],
        dtype=np.float64,
    )
    centroid, normal = CollisionDecomposer.compute_pca_splitting_plane(coords)

    # Centroid should be exactly (0.0, 0.0, 0.0)
    assert math.isclose(centroid.x, 0.0, abs_tol=1e-3)
    assert math.isclose(centroid.y, 0.0, abs_tol=1e-3)
    assert math.isclose(centroid.z, 0.0, abs_tol=1e-3)

    # Normal should be unit length
    assert math.isclose(normal.length, 1.0, rel_tol=1e-3)
    # Principal axis of variance is X axis -> normal should be parallel to (1, 0, 0)
    assert abs(normal.x) > 0.9


def test_pca_splitting_plane_edge_cases():
    # Empty coords
    c_empty, n_empty = CollisionDecomposer.compute_pca_splitting_plane(np.zeros((0, 3)))
    assert c_empty.length == 0.0
    assert math.isclose(n_empty.length, 1.0, rel_tol=1e-3)

    # Single point
    coords_one = np.array([[1.0, 2.0, 3.0]])
    c_one, n_one = CollisionDecomposer.compute_pca_splitting_plane(coords_one)
    assert math.isclose(c_one.x, 1.0)
    assert math.isclose(c_one.y, 2.0)
    assert math.isclose(c_one.z, 3.0)
    assert math.isclose(n_one.length, 1.0, rel_tol=1e-3)


def test_measure_hull_concavity_null_safety():
    assert CollisionDecomposer.measure_hull_concavity(None, None) == 0.0


def test_harden_convex_hull_null_and_empty():
    assert CollisionDecomposer.harden_convex_hull(None, 32) is False


def test_decompose_mesh_null_safety():
    assert CollisionDecomposer.decompose_mesh_to_hulls(None, 4) == []


def test_map_collider_name_for_engine():
    base = "FighterJet"

    # UE5
    assert CollisionManager.map_collider_name_for_engine(base, 1, "UE5") == "UCX_FighterJet_01"
    assert CollisionManager.map_collider_name_for_engine(base, 12, "UE5") == "UCX_FighterJet_12"

    # Godot 4
    assert CollisionManager.map_collider_name_for_engine(base, 1, "GODOT_4") == "FighterJet_Collider_01-convcol"
    assert CollisionManager.map_collider_name_for_engine(base, 5, "GODOT_4") == "FighterJet_Collider_05-convcol"

    # Unity 6
    assert CollisionManager.map_collider_name_for_engine(base, 1, "UNITY_6") == "FighterJet_Collider_01"

    # MSFS 2024
    assert CollisionManager.map_collider_name_for_engine(base, 1, "MSFS_2024") == "FighterJet_Collider_01"


def test_collision_manager_null_mesh_objs():
    assert CollisionManager.generate_colliders_for_objects([], "Test") == []
    assert CollisionManager.remove_colliders_for_objects([], "Test") == 0
