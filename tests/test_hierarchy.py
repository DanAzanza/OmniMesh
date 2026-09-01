"""
Unit tests for OmniMesh Hierarchy & Multi-Mesh Consolidation Module.
"""

from __future__ import annotations

from core.hierarchy import MeshMergeEngine, get_rest_world_matrix_for_static


class DummyBone:
    def __init__(self, name: str, matrix_local: list[list[float]] | None = None):
        self.name = name
        self.matrix_local = matrix_local or [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


class DummyArmatureData:
    def __init__(self, bones: dict[str, DummyBone]):
        self.bones = bones


class DummyArmature:
    def __init__(self, bones: dict[str, DummyBone]):
        self.type = "ARMATURE"
        self.data = DummyArmatureData(bones)
        self.matrix_world = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


class DummyObject:
    def __init__(self, matrix_world: list[list[float]]):
        self.type = "MESH"
        self.matrix_world = matrix_world
        self.matrix_parent_inverse = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        self.matrix_basis = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        self.material_slots = []
        self.vertex_groups = []
        self.data = None


def test_get_rest_world_matrix_for_static_null():
    assert get_rest_world_matrix_for_static(None, None, "root") is None


def test_get_rest_world_matrix_for_static_no_armature():
    m = [[1, 0, 0, 5], [0, 1, 0, 2], [0, 0, 1, 3], [0, 0, 0, 1]]
    obj = DummyObject(m)
    res = get_rest_world_matrix_for_static(obj, None, "bone")
    assert res == m


def test_consolidate_and_merge_meshes_null_or_empty():
    assert MeshMergeEngine.consolidate_and_merge_meshes([], "Merged") is None
    assert MeshMergeEngine.consolidate_and_merge_meshes(None, "Merged") is None
