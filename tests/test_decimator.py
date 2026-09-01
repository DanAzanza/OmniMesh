"""
Unit tests for OmniMesh Decimation & Simplification Engine.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from core.decimator import MeshDecimator


class MockVert:
    def __init__(self, index: int, co: tuple[float, float, float] = (0.0, 0.0, 0.0)):
        self.index = index
        self.co = co
        self.is_valid = True
        self.link_edges: list[MockEdge] = []
        self.link_faces: list[MockFace] = []
        self._deform_dict: dict[int, float] = {}

    def __getitem__(self, item: Any) -> Any:
        return self._deform_dict


class MockEdge:
    def __init__(
        self, verts: tuple[MockVert, MockVert], is_boundary: bool = False, seam: bool = False, smooth: bool = True
    ):
        self.verts = verts
        self.is_valid = True
        self.is_boundary = is_boundary
        self.seam = seam
        self.smooth = smooth
        self.link_faces: list[MockFace] = []
        for v in verts:
            v.link_edges.append(self)


class MockUVLoop:
    def __init__(self, vert: MockVert, uv: tuple[float, float] = (0.0, 0.0)):
        self.vert = vert
        self._uv_data = {0: MagicMock(uv=uv)}

    def __getitem__(self, item: Any) -> Any:
        return self._uv_data.get(item, MagicMock(uv=(0.0, 0.0)))


class MockFace:
    def __init__(
        self, verts: list[MockVert], material_index: int = 0, normal: tuple[float, float, float] = (0.0, 0.0, 1.0)
    ):
        self.verts = verts
        self.is_valid = True
        self.material_index = material_index
        self.smooth = True
        self.normal = normal
        self.edges: list[MockEdge] = []
        self.loops: list[MockUVLoop] = [MockUVLoop(v) for v in verts]
        for v in verts:
            v.link_faces.append(self)


class MockBMesh:
    def __init__(self, verts: list[MockVert], edges: list[MockEdge], faces: list[MockFace]):
        self.verts = MagicMock()
        self.verts.__iter__ = lambda self: iter(verts)
        self.verts.__len__ = lambda self: len(verts)
        self.verts.ensure_lookup_table = MagicMock()
        self.verts.index_update = MagicMock()

        self.edges = MagicMock()
        self.edges.__iter__ = lambda self: iter(edges)
        self.edges.__len__ = lambda self: len(edges)
        self.edges.ensure_lookup_table = MagicMock()
        self.edges.index_update = MagicMock()

        self.faces = MagicMock()
        self.faces.__iter__ = lambda self: iter(faces)
        self.faces.__len__ = lambda self: len(faces)
        self.faces.ensure_lookup_table = MagicMock()
        self.faces.index_update = MagicMock()

        self.loops = MagicMock()
        self.loops.layers = MagicMock()
        self.loops.layers.uv = {0: 0}


def test_tag_boundaries_and_uv_seams_null():
    assert MeshDecimator.tag_boundaries_and_uv_seams(None) == set()
    assert MeshDecimator.tag_boundaries_and_uv_seams(MagicMock(verts=None)) == set()


def test_tag_boundaries_and_uv_seams_with_boundaries_and_materials():
    v0 = MockVert(0, (0, 0, 0))
    v1 = MockVert(1, (1, 0, 0))
    v2 = MockVert(2, (1, 1, 0))
    v3 = MockVert(3, (0, 1, 0))

    e01 = MockEdge((v0, v1), is_boundary=True)
    e12 = MockEdge((v1, v2), seam=True)
    e23 = MockEdge((v2, v3), smooth=False)
    e30 = MockEdge((v3, v0), is_boundary=False)

    f1 = MockFace([v0, v1, v2], material_index=0)
    f2 = MockFace([v0, v2, v3], material_index=1)
    e30.link_faces = [f1, f2]

    bm = MockBMesh([v0, v1, v2, v3], [e01, e12, e23, e30], [f1, f2])

    pinned = MeshDecimator.tag_boundaries_and_uv_seams(bm)
    # v0, v1 tagged by boundary e01
    assert 0 in pinned
    assert 1 in pinned
    # v1, v2 tagged by seam e12
    assert 2 in pinned
    # v2, v3 tagged by sharp e23
    assert 3 in pinned


def test_tag_boundaries_uv_discontinuity():
    v0 = MockVert(0)
    v1 = MockVert(1)
    e01 = MockEdge((v0, v1), is_boundary=False)

    f1 = MockFace([v0, v1], material_index=0)
    f2 = MockFace([v0, v1], material_index=0)
    e01.link_faces = [f1, f2]

    # UV discontinuity on v0
    f1.loops[0]._uv_data[0] = MagicMock(uv=(0.0, 0.0))
    f2.loops[0]._uv_data[0] = MagicMock(uv=(1.0, 1.0))
    f1.loops[1]._uv_data[0] = MagicMock(uv=(0.5, 0.5))
    f2.loops[1]._uv_data[0] = MagicMock(uv=(0.5, 0.5))

    bm = MockBMesh([v0, v1], [e01], [f1, f2])
    pinned = MeshDecimator.tag_boundaries_and_uv_seams(bm)
    assert 0 in pinned
    assert 1 in pinned


def test_apply_planar_limited_dissolve_null_or_zero():
    MeshDecimator.apply_planar_limited_dissolve(None, 0.0)
    MeshDecimator.apply_planar_limited_dissolve(None, 0.5)
    mock_bm = MagicMock()
    mock_bm.faces = []
    MeshDecimator.apply_planar_limited_dissolve(mock_bm, 0.5)


def test_inject_curvature_weights_null_and_mock():
    MeshDecimator.inject_curvature_weights(None, None, set())

    mock_obj = MagicMock()
    mock_obj.vertex_groups.get.return_value = None
    mock_vg = MagicMock()
    mock_vg.index = 0
    mock_obj.vertex_groups.new.return_value = mock_vg

    v0 = MockVert(0)
    v1 = MockVert(1)
    e01 = MockEdge((v0, v1))
    f1 = MockFace([v0, v1], normal=(0, 0, 1))
    f2 = MockFace([v0, v1], normal=(0, 1, 0))
    e01.link_faces = [f1, f2]

    bm = MockBMesh([v0, v1], [e01], [f1, f2])
    bm.verts.layers.deform.verify.return_value = 0

    MeshDecimator.inject_curvature_weights(mock_obj, bm, pinned_vert_indices={1})
    # Pinned vertex receives weight 1.0
    assert v1._deform_dict[0] == 1.0


def test_execute_decimate_qem_guards():
    # Null or non-mesh
    MeshDecimator.execute_decimate_qem(None, 0.5)
    mock_obj = MagicMock()
    mock_obj.type = "EMPTY"
    MeshDecimator.execute_decimate_qem(mock_obj, 0.5)

    # Ratio >= 0.999 (should clean vertex group and return)
    mock_mesh_obj = MagicMock()
    mock_mesh_obj.type = "MESH"
    mock_vg = MagicMock()
    mock_mesh_obj.vertex_groups.get.return_value = mock_vg
    MeshDecimator.execute_decimate_qem(mock_mesh_obj, 1.0)
    mock_mesh_obj.vertex_groups.remove.assert_called_with(mock_vg)


def test_prepare_and_clean_shape_keys():
    MeshDecimator.prepare_and_clean_shape_keys(None, purge=True)

    mock_obj = MagicMock()
    mock_kb1 = MagicMock()
    mock_kb1.value = 0.75
    mock_kb2 = MagicMock()
    mock_kb2.value = 0.5
    mock_obj.data.shape_keys.key_blocks = [mock_kb1, mock_kb2]

    MeshDecimator.prepare_and_clean_shape_keys(mock_obj, purge=False)
    assert mock_kb1.value == 0.0
    assert mock_kb2.value == 0.0
