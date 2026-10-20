"""
Unit tests for OmniMesh Mesh Sanitizer & 3-Tier Topology Repair Engine.
"""

from __future__ import annotations
from typing import TYPE_CHECKING as _TC, Any as _Any

if _TC:
    _MockBase: type[_Any] = object
else:
    _MockBase = object

from typing import Any
from unittest.mock import MagicMock
import pytest

from core.sanitizer import MeshSanitizer, SanitizeOptions, Vector
from core.topology_repair import TopologyRepairOptions


class MockSanitizerVert(_MockBase):
    def __init__(self, index: int, co: tuple[float, float, float] = (0.0, 0.0, 0.0)):
        self.index = index
        self.co = Vector(co)
        self.is_valid = True
        self.link_edges: list[MockSanitizerEdge] = []
        self.link_faces: list[MockSanitizerFace] = []
        self._deform_dict: dict[int, float] = {}

    def __getitem__(self, item: Any) -> Any:
        return self._deform_dict


class MockSanitizerEdge(_MockBase):
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


class MockSanitizerUVLoop(_MockBase):
    def __init__(self, vert: MockSanitizerVert, uv: tuple[float, float] = (0.0, 0.0)):
        self.vert = vert
        self._uv_data = {0: MagicMock(uv=Vector(uv))}

    def __getitem__(self, item: Any) -> Any:
        return self._uv_data.get(item, MagicMock(uv=Vector((0.0, 0.0))))


class MockSanitizerFace(_MockBase):
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
        options=TopologyRepairOptions(
            enable_weld=True,
            enable_split_non_manifold=True,
            enable_fill_holes=True,
            enable_triangulate_ngons=True,
            enable_cull_micro_islands=True,
        ),
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
    assert MeshSanitizer.sanitize_mesh_full(None, options=SanitizeOptions(epsilon_merge=1e-5, w_crit=0.01)) == {}


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


def test_split_non_manifold_edges_raises_topology_error_on_corrupted_rollback():
    from core.exceptions import TopologyError
    from core.topology_repair import TopologyRepairEngine

    mock_bm = MagicMock()
    mock_edge = MagicMock()
    mock_edge.is_valid = True
    v1, v2 = MagicMock(), MagicMock()
    v1.co = Vector((0, 0, 0))
    v2.co = Vector((1, 0, 0))
    mock_edge.verts = (v1, v2)

    face1, face2, face3 = MagicMock(), MagicMock(), MagicMock()
    for f in (face1, face2, face3):
        f.is_valid = True
        f.verts = [v1, v2, MagicMock()]
        f.loops = []
        f.material_index = 0
        f.smooth = True

    mock_edge.link_faces = [face1, face2, face3]
    mock_edges = MagicMock()
    mock_edges.__iter__.return_value = [mock_edge]
    mock_bm.edges = mock_edges

    mock_bm.faces.new.side_effect = RuntimeError("BMesh internal failure")

    with pytest.raises(TopologyError, match="Catastrophic topology corruption"):
        TopologyRepairEngine.split_non_manifold_edges(mock_bm)


def test_split_non_manifold_edges_rollback_recovery_succeeds():
    from core.topology_repair import TopologyRepairEngine

    mock_bm = MagicMock()
    mock_edge = MagicMock()
    mock_edge.is_valid = True
    v1, v2 = MagicMock(), MagicMock()
    v1.co = Vector((0, 0, 0))
    v2.co = Vector((1, 0, 0))
    mock_edge.verts = (v1, v2)

    face1, face2, face3 = MagicMock(), MagicMock(), MagicMock()
    for f in (face1, face2, face3):
        f.is_valid = True
        f.verts = [v1, v2, MagicMock()]
        f.loops = []
        f.material_index = 0
        f.smooth = True

    mock_edge.link_faces = [face1, face2, face3]
    mock_edges = MagicMock()
    mock_edges.__iter__.return_value = [mock_edge]
    mock_bm.edges = mock_edges

    restored_face = MagicMock()
    mock_bm.faces.new.side_effect = [RuntimeError("New face failed"), restored_face]

    splits = TopologyRepairEngine.split_non_manifold_edges(mock_bm)
    assert splits == 0
    assert mock_bm.faces.new.call_count == 2


def test_remap_fan_raises_topology_error_on_corrupted_rollback():
    from core.exceptions import TopologyError
    from core.topology_repair import _remap_fan_to_new_vertex

    mock_bm = MagicMock()
    mock_face = MagicMock()
    mock_face.is_valid = True
    v_orig = MagicMock()
    mock_face.verts = [v_orig, MagicMock(), MagicMock()]
    mock_face.loops = []

    v_new = MagicMock()
    mock_bm.faces.new.side_effect = RuntimeError("BMesh geometry creation error")

    with pytest.raises(TopologyError, match="Catastrophic topology corruption"):
        _remap_fan_to_new_vertex(mock_bm, [mock_face], v_orig, v_new, [])
