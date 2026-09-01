"""
Unit tests for OmniMesh Mesh Sanitizer Module.
"""

from __future__ import annotations

from core.sanitizer import MeshSanitizer


def test_clean_loose_and_degenerates_null():
    stats = MeshSanitizer.clean_loose_and_degenerates(None)
    assert stats == {"loose_verts": 0, "wire_edges": 0, "zero_edges": 0, "zero_faces": 0}


def test_merge_doubles_boundary_safe_null():
    assert MeshSanitizer.merge_doubles_boundary_safe(None) == 0


def test_split_bowtie_vertices_null():
    assert MeshSanitizer.split_bowtie_vertices(None) == 0


def test_cull_subpixel_islands_null():
    assert MeshSanitizer.cull_subpixel_islands(None, 0.1) == 0
    assert MeshSanitizer.cull_subpixel_islands(None, 0.0) == 0


def test_sanitize_mesh_full_null():
    assert MeshSanitizer.sanitize_mesh_full(None, 1e-5, 0.01) == {}
