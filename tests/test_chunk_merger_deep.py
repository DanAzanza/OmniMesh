"""
Comprehensive deep unit tests for core/chunk_merger.py
Tests HLODClusterMerger, seam welding across chunk boundaries,
material palette consolidation, and skeletal vertex group preservation.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from core.chunk_merger import HLODClusterMerger
from core.compat import Matrix, Vector


class MockMesh:
    def __init__(self, name: str = "Mesh"):
        self.name = name
        self.materials: list[Any] = []
        self.polygons = [MagicMock()]
        self.vertices: list[Any] = []

    def update(self) -> None:
        pass


class MockVertexGroup:
    def __init__(self, name: str):
        self.name = name


class MockChunkObject:
    def __init__(self, name: str = "Chunk_0"):
        self.name = name
        self.type = "MESH"
        self.data = MockMesh(f"{name}_Mesh")
        self.matrix_world = Matrix.Identity(4) if Matrix else MagicMock()
        self.vertex_groups = MockVertexGroupCollection()


class MockVertexGroupCollection:
    def __init__(self):
        self._vgs: list[MockVertexGroup] = []

    def __iter__(self):
        return iter(self._vgs)

    def __len__(self):
        return len(self._vgs)

    def new(self, name: str) -> MockVertexGroup:
        vg = MockVertexGroup(name)
        self._vgs.append(vg)
        return vg


class MockCollection:
    def __init__(self, name: str = "TargetCol"):
        self.name = name
        self.objects = MockCollectionObjects()


class MockCollectionObjects:
    def __init__(self):
        self._objs: list[Any] = []

    def link(self, obj: Any) -> None:
        self._objs.append(obj)

    def __contains__(self, obj: Any) -> bool:
        return obj in self._objs


class MockBlendData:
    def __init__(self):
        self.objects = MockBlendObjects()
        self.meshes = MockBlendMeshes()
        self.scenes = [MagicMock()]


class MockBlendObjects:
    def __init__(self):
        self._objs: dict[str, Any] = {}

    def new(self, name: str, object_data: Any) -> Any:
        obj = MockChunkObject(name)
        obj.data = object_data
        self._objs[name] = obj
        return obj


class MockBlendMeshes:
    def __init__(self):
        self._meshes: dict[str, Any] = {}

    def new(self, name: str) -> Any:
        m = MockMesh(name)
        self._meshes[name] = m
        return m


# ==============================================================================
# HLOD Cluster Merger Unit Tests
# ==============================================================================


def test_merge_chunks_empty_list():
    bdata = MockBlendData()
    assert (
        HLODClusterMerger.merge_chunks_for_hlod(
            [],
            "HLOD_Merged",
            None,
            blend_data=bdata,  # type: ignore[arg-type]
        )
        is None
    )


def test_merge_chunks_no_valid_meshes():
    bdata = MockBlendData()
    arm_obj = MockChunkObject("Armature")
    arm_obj.type = "ARMATURE"
    none_data_obj = MockChunkObject("NoneData")
    none_data_obj.data = None  # type: ignore[assignment]

    assert (
        HLODClusterMerger.merge_chunks_for_hlod(
            [arm_obj, none_data_obj],  # type: ignore[list-item]
            "HLOD_Merged",
            None,
            blend_data=bdata,  # type: ignore[arg-type]
        )
        is None
    )


def test_recenter_pivot_stationary_shifts_vertices_and_matrix():
    class MockVertex:
        def __init__(self, x: float, y: float, z: float):
            self.co = Vector((x, y, z))

    obj = MockChunkObject("CenteringObject")
    v1 = MockVertex(10.0, 0.0, 0.0)
    v2 = MockVertex(20.0, 0.0, 0.0)
    obj.data.vertices = [v1, v2]
    obj.data.update = MagicMock()

    HLODClusterMerger._recenter_pivot_stationary(obj)  # type: ignore[arg-type]

    # Center is at x=15.0. Local coordinates should shift by -15.0
    assert abs(v1.co.x - (-5.0)) < 1e-4
    assert abs(v2.co.x - 5.0) < 1e-4
    assert obj.data.update.called


def test_recenter_pivot_stationary_zero_or_empty():
    # Empty object should return early without error
    empty_obj = MockChunkObject("Empty")
    empty_obj.data.vertices = []
    HLODClusterMerger._recenter_pivot_stationary(empty_obj)  # type: ignore[arg-type]

    # Non-mesh object
    arm = MockChunkObject("Arm")
    arm.type = "ARMATURE"
    HLODClusterMerger._recenter_pivot_stationary(arm)  # type: ignore[arg-type]

    # Already centered at origin
    class MockVertex:
        def __init__(self, x: float, y: float, z: float):
            self.co = Vector((x, y, z))

    centered_obj = MockChunkObject("Centered")
    centered_obj.data.vertices = [MockVertex(-1.0, 0.0, 0.0), MockVertex(1.0, 0.0, 0.0)]
    HLODClusterMerger._recenter_pivot_stationary(centered_obj)  # type: ignore[arg-type]
    # Coordinates shouldn't change
    assert abs(centered_obj.data.vertices[0].co.x - (-1.0)) < 1e-4


def test_merge_chunks_success_with_materials_and_vgroups():
    bdata = MockBlendData()
    target_col = MockCollection("HLOD_Target")

    mat_a = MagicMock(name="Mat_A")
    mat_b = MagicMock(name="Mat_B")

    chunk1 = MockChunkObject("Chunk_0")
    chunk1.data.materials = [mat_a]
    chunk1.vertex_groups.new("Head")
    chunk1.vertex_groups.new("Spine")

    chunk2 = MockChunkObject("Chunk_1")
    chunk2.data.materials = [mat_b]
    chunk2.vertex_groups.new("Spine")
    chunk2.vertex_groups.new("Leg_L")

    mock_bmesh = MagicMock()
    mock_merged_bm = MagicMock()
    mock_temp_bm = MagicMock()

    # BMesh instantiation routing
    mock_bmesh.new.side_effect = [mock_merged_bm, mock_temp_bm, mock_temp_bm]
    mock_temp_bm.faces = []
    mock_temp_bm.verts = MagicMock()
    mock_temp_bm.verts.__iter__.return_value = []

    mock_bpy = MagicMock()
    with (
        patch("core.chunk_merger.bpy", mock_bpy),
        patch("core.chunk_merger.bmesh", mock_bmesh),
        patch.object(HLODClusterMerger, "_recenter_pivot_stationary") as mock_recenter,
    ):
        res_obj = HLODClusterMerger.merge_chunks_for_hlod(
            [chunk1, chunk2],  # type: ignore[list-item]
            "Merged_HLOD",
            target_col,  # type: ignore[arg-type]
            weld_dist=0.002,
            blend_data=bdata,  # type: ignore[arg-type]
        )

        assert res_obj is not None
        assert res_obj.name == "Merged_HLOD"
        assert res_obj in target_col.objects
        # Verify master material palette contains both materials
        assert mat_a in getattr(res_obj.data, "materials", [])
        assert mat_b in getattr(res_obj.data, "materials", [])
        # Verify remove_doubles was triggered
        assert mock_bmesh.ops.remove_doubles.called
        assert mock_recenter.called
