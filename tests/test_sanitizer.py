"""
Unit tests for OmniMesh Mesh Sanitizer & 3-Tier Topology Repair Engine.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
import pytest

from core.sanitizer import MeshSanitizer, Vector


class MockSanitizerVert:
    def __init__(self, index: int, co: tuple[float, float, float] = (0.0, 0.0, 0.0)):
        self.index = index
        self.co = Vector(co)
        self.is_valid = True
        self.link_edges: list[MockSanitizerEdge] = []
        self.link_faces: list[MockSanitizerFace] = []
        self._deform_dict: dict[int, float] = {}

    def __getitem__(self, item: Any) -> Any:
        return self._deform_dict


class MockSanitizerEdge:
    def __init__(self, verts: tuple[MockSanitizerVert, MockSanitizerVert], is_boundary: bool = False):
        self.verts = verts
        self.is_valid = True
        self.is_boundary = is_boundary
        self.link_faces: list[MockSanitizerFace] = []
        for v in verts:
            v.link_edges.append(self)

    def calc_length(self) -> float:
        v0, v1 = self.verts
        return (v0.co - v1.co).length


class MockSanitizerUVLoop:
    def __init__(self, vert: MockSanitizerVert, uv: tuple[float, float] = (0.0, 0.0)):
        self.vert = vert
        self._uv_data = {0: MagicMock(uv=Vector(uv))}

    def __getitem__(self, item: Any) -> Any:
        return self._uv_data.get(item, MagicMock(uv=Vector((0.0, 0.0))))


class MockSanitizerFace:
    def __init__(
        self,
        verts: list[MockSanitizerVert],
        normal: tuple[float, float, float] = (0.0, 0.0, 1.0),
        material_index: int = 0,
    ):
        self.verts = verts
        self.is_valid = True
        self.normal = Vector(normal)
        self.material_index = material_index
        self.smooth = True
        self.edges: list[MockSanitizerEdge] = []
        self.loops: list[MockSanitizerUVLoop] = [MockSanitizerUVLoop(v) for v in verts]
        for v in verts:
            v.link_faces.append(self)

    def calc_area(self) -> float:
        return 1.0


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


def test_fallback_vector_operations():
    v1 = Vector((1.0, 2.0, 3.0))
    v2 = Vector((4.0, 5.0, 6.0))
    assert v1.x == 1.0
    assert v1.y == 2.0
    assert v1.z == 3.0
    assert v1.dot(v2) == 1.0 * 4.0 + 2.0 * 5.0 + 3.0 * 6.0
    diff = v2 - v1
    assert diff.x == 3.0
    assert diff.y == 3.0
    assert diff.z == 3.0
    assert pytest.approx(diff.length) == (3.0**2 + 3.0**2 + 3.0**2) ** 0.5


def test_purge_duplicate_faces_empty_and_null():
    assert MeshSanitizer._purge_duplicate_faces(None) == 0
    mock_bm = MagicMock()
    mock_bm.faces = []
    assert MeshSanitizer._purge_duplicate_faces(mock_bm) == 0
