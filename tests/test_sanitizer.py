"""
Unit tests for OmniMesh Mesh Sanitizer & 3-Tier Topology Repair Engine.
"""

from __future__ import annotations

from core.sanitizer import MeshSanitizer


def test_tier0_pure_hygiene_null():
    stats = MeshSanitizer.execute_tier0_pure_hygiene(None)
    assert stats == {
        "zero_faces": 0,
        "zero_edges": 0,
        "wire_edges": 0,
        "loose_verts": 0,
        "duplicate_faces": 0,
    }


def test_merge_doubles_boundary_safe_null():
    assert MeshSanitizer.merge_doubles_boundary_safe(None) == 0
    assert MeshSanitizer.merge_doubles_boundary_safe(None, dist=0.0) == 0


def test_split_bowtie_vertices_null():
    assert MeshSanitizer.split_bowtie_vertices(None) == 0


def test_split_non_manifold_edges_null():
    assert MeshSanitizer.split_non_manifold_edges(None) == 0


def test_fill_small_boundary_holes_null():
    assert MeshSanitizer.fill_small_boundary_holes(None, max_edges=4) == 0
    assert MeshSanitizer.fill_small_boundary_holes(None, max_edges=2) == 0


def test_cull_subpixel_islands_null():
    assert MeshSanitizer.cull_subpixel_islands(None, 0.1) == 0
    assert MeshSanitizer.cull_subpixel_islands(None, 0.0) == 0


def test_tier1_topological_repair_null():
    stats = MeshSanitizer.execute_tier1_topological_repair(
        None,
        enable_weld=True,
        enable_split_non_manifold=True,
        enable_fill_holes=True,
        enable_triangulate_ngons=True,
        enable_cull_micro_islands=True,
    )
    assert stats == {
        "welded_verts": 0,
        "split_bowties": 0,
        "split_non_manifold_edges": 0,
        "filled_holes": 0,
        "triangulated_ngons": 0,
        "culled_islands": 0,
    }


def test_tier2_pipeline_guards_null():
    stats_manifold = MeshSanitizer.execute_tier2_pipeline_guards(None, normal_recalc_policy="MANIFOLD_ONLY")
    assert stats_manifold == {"recalculated_normals": False}

    stats_force = MeshSanitizer.execute_tier2_pipeline_guards(None, normal_recalc_policy="FORCE_ALL")
    assert stats_force == {"recalculated_normals": False}

    stats_off = MeshSanitizer.execute_tier2_pipeline_guards(None, normal_recalc_policy="OFF")
    assert stats_off == {"recalculated_normals": False}


def test_sanitize_mesh_full_null():
    assert MeshSanitizer.sanitize_mesh_full(None, 1e-5, 0.01) == {}
