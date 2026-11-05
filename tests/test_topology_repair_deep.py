"""
Comprehensive deep unit tests for core/topology_repair.py
Tests bowtie splitting, non-manifold edge resolution, boundary hole filling,
subpixel island culling, and full Tier 1 topological repair orchestration.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from core.compat import Vector
from core.exceptions import TopologyError
from core.topology_repair import (
    TopologyRepairEngine,
    TopologyRepairOptions,
    _find_connected_face_fans,
    _remap_fan_to_new_vertex,
)


class MockVert:
    def __init__(self, co: tuple[float, float, float] = (0.0, 0.0, 0.0)):
        self.co = Vector(co)
        self.is_valid = True
        self.link_faces: list[MockFace] = []
        self._layers: dict[Any, Any] = {}

    def __getitem__(self, lay: Any):
        return self._layers.get(lay, {})

    def __setitem__(self, lay: Any, val: Any):
        self._layers[lay] = val


class MockEdge:
    def __init__(self, v1: MockVert, v2: MockVert):
        self.verts = [v1, v2]
        self.link_faces: list[MockFace] = []
        self.is_valid = True
        self.is_boundary = False


class MockLoop:
    def __init__(self, vert: MockVert):
        self.vert = vert
        self._layers: dict[Any, Any] = {}

    def __getitem__(self, lay: Any):
        m = MagicMock()
        m.uv = Vector((0.0, 0.0))
        return self._layers.get(lay, m)


class MockFace:
    def __init__(self, verts: list[MockVert], edges: list[MockEdge] | None = None):
        self.verts = verts
        self.edges = edges or []
        self.is_valid = True
        self.material_index = 0
        self.smooth = True
        self.loops = [MockLoop(v) for v in verts]
        for v in verts:
            v.link_faces.append(self)
        for e in self.edges:
            e.link_faces.append(self)

    def calc_area(self) -> float:
        return 0.1


class MockBMeshLookup:
    def __init__(self, items: list[Any]):
        self.items = items

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    def __getitem__(self, idx: int | slice):
        return self.items[idx]

    def ensure_lookup_table(self) -> None:
        pass

    def index_update(self) -> None:
        pass

    def new(self, *args, **kwargs):
        pass

    def remove(self, item: Any):
        if item in self.items:
            self.items.remove(item)


class MockBMeshSimple:
    def __init__(self):
        self.verts = MockBMeshLookup([])
        self.edges = MockBMeshLookup([])
        self.faces = MockBMeshLookup([])
        self.loops = MagicMock()
        self.loops.layers.uv.values.return_value = []


# ==============================================================================
# 1. Face Fan Partitioning Tests
# ==============================================================================


def test_find_connected_face_fans_empty():
    vert = MockVert()
    assert _find_connected_face_fans(vert) == []  # type: ignore[arg-type]


def test_find_connected_face_fans_single_fan():
    v_center = MockVert()
    v1 = MockVert((1.0, 0.0, 0.0))
    v2 = MockVert((0.0, 1.0, 0.0))
    v3 = MockVert((-1.0, 0.0, 0.0))

    e1 = MockEdge(v_center, v1)
    e2 = MockEdge(v_center, v2)
    e3 = MockEdge(v_center, v3)

    f1 = MockFace([v_center, v1, v2], [e1, e2])
    f2 = MockFace([v_center, v2, v3], [e2, e3])

    fans = _find_connected_face_fans(v_center)  # type: ignore[arg-type]
    assert len(fans) == 1
    assert set(fans[0]) == {f1, f2}


def test_find_connected_face_fans_bowtie_two_fans():
    v_center = MockVert()
    v1 = MockVert((1.0, 0.0, 0.0))
    v2 = MockVert((0.0, 1.0, 0.0))
    v3 = MockVert((-1.0, 0.0, 0.0))
    v4 = MockVert((0.0, -1.0, 0.0))

    # Fan 1
    e1 = MockEdge(v_center, v1)
    e2 = MockEdge(v_center, v2)
    f1 = MockFace([v_center, v1, v2], [e1, e2])

    # Fan 2 (completely disconnected edge sharing from Fan 1)
    e3 = MockEdge(v_center, v3)
    e4 = MockEdge(v_center, v4)
    f2 = MockFace([v_center, v3, v4], [e3, e4])

    fans = _find_connected_face_fans(v_center)  # type: ignore[arg-type]
    assert len(fans) == 2
    fan_sets = [set(f) for f in fans]
    assert {f1} in fan_sets
    assert {f2} in fan_sets


# ==============================================================================
# 2. Fan Remapping Tests
# ==============================================================================


def test_remap_fan_to_new_vertex_success():
    bm = MockBMeshSimple()
    v_old = MockVert((0.0, 0.0, 0.0))
    v1 = MockVert((1.0, 0.0, 0.0))
    v2 = MockVert((0.0, 1.0, 0.0))
    face = MockFace([v_old, v1, v2])
    bm.faces.items.append(face)

    v_new = MockVert((0.0, 0.0, 0.0))

    new_face_mock = MockFace([v_new, v1, v2])
    bm.faces.new = MagicMock(return_value=new_face_mock)  # type: ignore[assignment]

    split = _remap_fan_to_new_vertex(bm, [face], v_old, v_new, [])  # type: ignore[arg-type]
    assert split == 1
    assert face not in bm.faces.items


def test_remap_fan_to_new_vertex_rollback_on_failure():
    bm = MockBMeshSimple()
    v_old = MockVert((0.0, 0.0, 0.0))
    v1 = MockVert((1.0, 0.0, 0.0))
    v2 = MockVert((0.0, 1.0, 0.0))
    face = MockFace([v_old, v1, v2])
    bm.faces.items.append(face)

    v_new = MockVert((0.0, 0.0, 0.0))

    # First call raises (remapping fails), second call succeeds (rollback)
    restored_face = MockFace([v_old, v1, v2])
    bm.faces.new = MagicMock(side_effect=[ValueError("Invalid face"), restored_face])  # type: ignore[assignment]

    split = _remap_fan_to_new_vertex(bm, [face], v_old, v_new, [])  # type: ignore[arg-type]
    assert split == 0


def test_remap_fan_to_new_vertex_catastrophic_error():
    bm = MockBMeshSimple()
    v_old = MockVert((0.0, 0.0, 0.0))
    v1 = MockVert((1.0, 0.0, 0.0))
    v2 = MockVert((0.0, 1.0, 0.0))
    face = MockFace([v_old, v1, v2])

    v_new = MockVert((0.0, 0.0, 0.0))
    # Both initial face and rollback face fail
    bm.faces.new = MagicMock(side_effect=[ValueError("Fail 1"), ValueError("Fail 2")])  # type: ignore[assignment]

    with pytest.raises(TopologyError, match="Catastrophic topology corruption"):
        _remap_fan_to_new_vertex(bm, [face], v_old, v_new, [])  # type: ignore[arg-type]


# ==============================================================================
# 3. Bowtie Splitting Engine Tests
# ==============================================================================


def test_split_bowtie_vertices_none_or_empty():
    assert TopologyRepairEngine.split_bowtie_vertices(None) == 0
    bm = MockBMeshSimple()
    assert TopologyRepairEngine.split_bowtie_vertices(bm) == 0  # type: ignore[arg-type]


def test_split_bowtie_vertices_manifold_no_op():
    bm = MockBMeshSimple()
    v = MockVert()
    v.link_faces = [MockFace([v])]
    bm.verts.items.append(v)
    assert TopologyRepairEngine.split_bowtie_vertices(bm) == 0  # type: ignore[arg-type]


def test_split_bowtie_vertices_two_fans_split():
    bm = MockBMeshSimple()
    v_center = MockVert()
    v1, v2, v3, v4 = MockVert(), MockVert(), MockVert(), MockVert()
    e1, e2 = MockEdge(v_center, v1), MockEdge(v_center, v2)
    e3, e4 = MockEdge(v_center, v3), MockEdge(v_center, v4)

    f1 = MockFace([v_center, v1, v2], [e1, e2])
    f2 = MockFace([v_center, v3, v4], [e3, e4])

    bm.verts.items.extend([v_center, v1, v2, v3, v4])
    bm.faces.items.extend([f1, f2])

    v_new = MockVert()
    bm.verts.new = MagicMock(return_value=v_new)  # type: ignore[assignment]
    new_face = MockFace([v_new, v3, v4])
    bm.faces.new = MagicMock(return_value=new_face)  # type: ignore[assignment]

    split_count = TopologyRepairEngine.split_bowtie_vertices(bm)  # type: ignore[arg-type]
    assert split_count >= 1


# ==============================================================================
# 4. Non-Manifold Edge Splitting Tests
# ==============================================================================


def test_split_non_manifold_edges_none_or_empty():
    assert TopologyRepairEngine.split_non_manifold_edges(None) == 0
    bm = MockBMeshSimple()
    assert TopologyRepairEngine.split_non_manifold_edges(bm) == 0  # type: ignore[arg-type]


def test_split_non_manifold_edges_three_faces_sharing_edge():
    bm = MockBMeshSimple()
    v1, v2 = MockVert((0.0, 0.0, 0.0)), MockVert((1.0, 0.0, 0.0))
    v3, v4, v5 = MockVert((0.0, 1.0, 0.0)), MockVert((0.0, -1.0, 0.0)), MockVert((0.0, 0.0, 1.0))

    shared_edge = MockEdge(v1, v2)
    f1 = MockFace([v1, v2, v3], [shared_edge])
    f2 = MockFace([v1, v2, v4], [shared_edge])
    f3 = MockFace([v1, v2, v5], [shared_edge])

    bm.verts.items.extend([v1, v2, v3, v4, v5])
    bm.edges.items.append(shared_edge)
    bm.faces.items.extend([f1, f2, f3])

    nv1, nv2 = MockVert(), MockVert()
    bm.verts.new = MagicMock(side_effect=[nv1, nv2])  # type: ignore[assignment]
    new_f3 = MockFace([nv1, nv2, v5])
    bm.faces.new = MagicMock(return_value=new_f3)  # type: ignore[assignment]

    split_count = TopologyRepairEngine.split_non_manifold_edges(bm)  # type: ignore[arg-type]
    assert split_count >= 1


# ==============================================================================
# 5. Boundary Hole Sealing Tests
# ==============================================================================


def test_fill_small_boundary_holes_none_or_invalid():
    assert TopologyRepairEngine.fill_small_boundary_holes(None, max_edges=4) == 0
    bm = MockBMeshSimple()
    assert TopologyRepairEngine.fill_small_boundary_holes(bm, max_edges=2) == 0  # type: ignore[arg-type]


def test_fill_small_boundary_holes_with_mocked_bmesh():
    bm = MockBMeshSimple()
    e = MockEdge(MockVert(), MockVert())
    e.is_boundary = True
    bm.edges.items.append(e)

    mock_bmesh = MagicMock()
    mock_bmesh.ops.holes_fill.return_value = {"faces": [MagicMock(), MagicMock()]}

    with patch("core.topology_repair.bmesh", mock_bmesh):
        filled = TopologyRepairEngine.fill_small_boundary_holes(bm, max_edges=4)  # type: ignore[arg-type]
        assert filled == 2
        mock_bmesh.ops.triangulate.assert_called_once()


# ==============================================================================
# 6. Subpixel Island Culling Tests
# ==============================================================================


def test_cull_subpixel_islands_none_or_empty():
    assert TopologyRepairEngine.cull_subpixel_islands(None, w_crit=0.01) == 0
    bm = MockBMeshSimple()
    assert TopologyRepairEngine.cull_subpixel_islands(bm, w_crit=0.01) == 0  # type: ignore[arg-type]


def test_cull_subpixel_islands_removes_tiny_island():
    bm = MockBMeshSimple()
    # Tiny island (diag < 0.01)
    v1, v2, v3 = MockVert((0.0, 0.0, 0.0)), MockVert((0.001, 0.0, 0.0)), MockVert((0.0, 0.001, 0.0))
    face_tiny = MockFace([v1, v2, v3])

    # Large island (diag >= 0.01)
    v4, v5, v6 = MockVert((10.0, 0.0, 0.0)), MockVert((20.0, 0.0, 0.0)), MockVert((10.0, 20.0, 0.0))
    face_large = MockFace([v4, v5, v6])

    bm.verts.items.extend([v1, v2, v3, v4, v5, v6])
    bm.faces.items.extend([face_tiny, face_large])

    mock_bmesh = MagicMock()
    with patch("core.topology_repair.bmesh", mock_bmesh):
        culled = TopologyRepairEngine.cull_subpixel_islands(bm, w_crit=0.05)  # type: ignore[arg-type]
        assert culled == 1
        mock_bmesh.ops.delete.assert_called_once()


# ==============================================================================
# 7. Tier 1 Orchestration Tests
# ==============================================================================


def test_execute_tier1_topological_repair_none():
    res = TopologyRepairEngine.execute_tier1_topological_repair(None)
    assert res["split_bowties"] == 0


def test_execute_tier1_topological_repair_orchestration():
    bm = MockBMeshSimple()
    opts = TopologyRepairOptions(
        enable_weld=True,
        enable_split_non_manifold=True,
        enable_fill_holes=True,
        enable_cull_micro_islands=True,
        enable_triangulate_ngons=True,
    )

    mock_bmesh = MagicMock()
    with (
        patch("core.topology_repair.bmesh", mock_bmesh),
        patch.object(TopologyRepairEngine, "split_bowtie_vertices", return_value=2),
        patch.object(TopologyRepairEngine, "split_non_manifold_edges", return_value=1),
        patch.object(TopologyRepairEngine, "fill_small_boundary_holes", return_value=3),
        patch.object(TopologyRepairEngine, "cull_subpixel_islands", return_value=4),
    ):
        res = TopologyRepairEngine.execute_tier1_topological_repair(bm, options=opts)  # type: ignore[arg-type]
        assert res["split_bowties"] == 2
        assert res["split_non_manifold_edges"] == 1
        assert res["filled_holes"] == 3
        assert res["culled_islands"] == 4
