"""
Unit tests for OmniMesh Hierarchy & Multi-Mesh Consolidation Module.
"""

from __future__ import annotations
from typing import TYPE_CHECKING as _TC, Any as _Any

if _TC:
    _MockBase: type[_Any] = object
else:
    _MockBase = object

from typing import Any, cast

from core.hierarchy import (
    CollectionCloneDAG,
    MeshMergeEngine,
    get_or_create_engine_import_collection,
    get_rest_world_matrix_for_static,
    safe_remove_collection_objects,
)
from tests.conftest import MockBlendData, MockMeshObject


class DummyBone(_MockBase):
    def __init__(self, name: str, matrix_local: Any = None):
        self.name = name
        self.matrix_local = matrix_local or [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]


class DummyArmatureData(_MockBase):
    def __init__(self, bones: dict[str, DummyBone]):
        self.bones = bones


class DummyArmature(_MockBase):
    def __init__(self, bones: dict[str, DummyBone]):
        self.type = "ARMATURE"
        self.data = DummyArmatureData(bones)
        self.matrix_world = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]


class DummyObject(_MockBase):
    def __init__(self, matrix_world: Any):
        self.type = "MESH"
        self.matrix_world = matrix_world
        self.matrix_parent_inverse = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        self.matrix_basis = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        self.material_slots = []
        self.vertex_groups = []
        self.data: Any = None


def test_get_rest_world_matrix_for_static_null():
    assert get_rest_world_matrix_for_static(None, None, "root") is None


def test_get_rest_world_matrix_for_static_no_armature():
    m = [[1, 0, 0, 5], [0, 1, 0, 2], [0, 0, 1, 3], [0, 0, 0, 1]]
    obj = DummyObject(m)
    res = get_rest_world_matrix_for_static(obj, None, "bone")
    assert res == m


def test_get_rest_world_matrix_for_static_missing_bone():
    bones = {"Root": DummyBone("Root")}
    arm = DummyArmature(bones)
    m = [[1, 0, 0, 1], [0, 1, 0, 1], [0, 0, 1, 1], [0, 0, 0, 1]]
    obj = DummyObject(m)
    # Target bone 'Hand' not in armature, fallback to static_obj.matrix_world
    res = get_rest_world_matrix_for_static(obj, arm, "Hand")
    assert res == m


def test_consolidate_and_merge_meshes_null_or_empty():
    assert MeshMergeEngine.consolidate_and_merge_meshes([], "Merged") is None
    assert MeshMergeEngine.consolidate_and_merge_meshes(cast(Any, None), "Merged") is None
    assert MeshMergeEngine.consolidate_and_merge_meshes(cast(Any, [None, object()]), "Merged") is None


def test_consolidate_and_merge_meshes_missing_blend_data_fails_closed():
    """Verify consolidate_and_merge_meshes returns None when blend_data is omitted."""
    dummy_mesh_obj = DummyObject([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
    dummy_mesh_obj.data = object()
    res = MeshMergeEngine.consolidate_and_merge_meshes([cast(Any, dummy_mesh_obj)], "Merged", blend_data=None)
    assert res is None


def test_collection_clone_dag_sibling_collection_lifecycle():
    """Verify CollectionCloneDAG creates, caches, and reparents sibling collections via MockBlendData."""
    bdata = MockBlendData()
    root_c = bdata.collections.new("Aircraft_LOD0")

    # 1. Tier 0 returns existing base
    c0 = CollectionCloneDAG.get_or_create_sibling_collection(root_c, 0, "Aircraft_LOD0", blend_data=cast(Any, bdata))
    assert c0 is root_c

    # 2. Tier 1 creates new sibling in bdata
    c1 = CollectionCloneDAG.get_or_create_sibling_collection(root_c, 1, "Aircraft", blend_data=cast(Any, bdata))
    assert c1 is not None
    assert c1.name == "Aircraft_LOD1"
    assert bdata.collections.get("Aircraft_LOD1") is c1

    # 3. Idempotent call returns cached instance
    c1_cached = CollectionCloneDAG.get_or_create_sibling_collection(root_c, 1, "Aircraft", blend_data=cast(Any, bdata))
    assert c1_cached is c1

    # 4. Missing blend_data fails closed
    assert CollectionCloneDAG.get_or_create_sibling_collection(root_c, 2, "Aircraft", blend_data=None) is None


def test_collection_clone_dag_wrap_loose_objects():
    """Verify wrap_loose_objects_into_root_collection groups objects and creates pivot with MockBlendData."""
    bdata = MockBlendData()
    obj1 = MockMeshObject("Prop1", poly_count=4)
    obj2 = MockMeshObject("Prop2", poly_count=4)

    coll, pivot = CollectionCloneDAG.wrap_loose_objects_into_root_collection(
        [cast(Any, obj1), cast(Any, obj2)],
        "PropAsset",
        blend_data=cast(Any, bdata),
    )
    assert coll is not None
    assert coll.name == "PropAsset"
    assert pivot is not None
    assert pivot.name == "PropAsset_Pivot"
    assert bdata.collections.get("PropAsset") is coll
    assert bdata.objects.get("PropAsset_Pivot") is pivot


def test_get_or_create_engine_import_collection_with_blend_data():
    """Verify engine import collections create root and nested subcollections via BlendData."""
    bdata = MockBlendData()
    scene = bdata.scenes[0]

    spatial_col = get_or_create_engine_import_collection(
        scene,
        "Vehicle",
        "SPATIAL",
        blend_data=cast(Any, bdata),
    )
    assert spatial_col is not None
    assert spatial_col.name == "Vehicle_Spatial"
    assert bdata.collections.get("Vehicle") is not None
    assert bdata.collections.get("Vehicle_Config") is not None
    assert bdata.collections.get("Vehicle_Spatial") is spatial_col


def test_safe_remove_collection_objects_with_blend_data():
    """Verify safe_remove_collection_objects cleans collection and deallocates datablocks via BlendData."""
    bdata = MockBlendData()
    col = bdata.collections.new("Temp_Col")
    obj = bdata.objects.new("Temp_Obj")
    col.objects.link(obj)

    removed = safe_remove_collection_objects(col, blend_data=cast(Any, bdata))
    assert removed == 1
    assert bdata.objects.get("Temp_Obj") is None
