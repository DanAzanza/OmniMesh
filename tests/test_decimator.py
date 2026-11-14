"""
Unit tests for OmniMesh Decimation & Simplification Engine.
"""

from __future__ import annotations
from typing import TYPE_CHECKING as _TC, Any as _Any

if _TC:
    _MockBase: type[_Any] = object
else:
    _MockBase = object

from unittest.mock import MagicMock
import pytest

from core.decimator import MeshDecimator
from core.exceptions import DecimationError
from core.lod_generator import generate_all_lods


from tests.conftest import MockBMesh, MockEdge, MockFace, MockVert


def test_tag_boundaries_and_uv_seams_null():
    assert MeshDecimator.tag_boundaries_and_uv_seams(None) == set()
    assert MeshDecimator.tag_boundaries_and_uv_seams(MagicMock(verts=None)) == set()


def test_tag_boundaries_and_uv_seams_corrupted_bmesh_raises():
    """Verify corrupted BMesh tables fail fast with DecimationError instead of silent empty return."""
    bm = MagicMock()
    bm.verts = MagicMock()
    bm.edges = MagicMock()
    bm.faces = MagicMock()
    bm.verts.ensure_lookup_table.side_effect = RuntimeError("Corrupted BMesh state")

    with pytest.raises(DecimationError) as exc_info:
        MeshDecimator.tag_boundaries_and_uv_seams(bm)
    assert "Corrupted BMesh state" in str(exc_info.value)


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


def test_apply_planar_limited_dissolve_failure_raises(monkeypatch):
    """Verify planar limited dissolve failure raises typed DecimationError."""
    mock_bmesh = MagicMock()
    mock_bmesh.ops.dissolve_limit.side_effect = RuntimeError("BMesh internal dissolve fault")
    monkeypatch.setattr("core.decimator.bmesh", mock_bmesh)

    bm = MagicMock()
    bm.verts = MagicMock()
    bm.edges = MagicMock()
    bm.faces = MagicMock()
    bm.faces.__len__.return_value = 4
    bm.edges.__len__.return_value = 6
    bm.edges.__getitem__.return_value = []
    bm.verts.__getitem__.return_value = []

    with pytest.raises(DecimationError) as exc_info:
        MeshDecimator.apply_planar_limited_dissolve(bm, 0.5)
    assert "BMesh internal dissolve fault" in str(exc_info.value)


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


def test_reset_shape_keys_and_purge_single_responsibility():
    # Null guard
    MeshDecimator.reset_shape_keys_to_basis(None)
    MeshDecimator.purge_all_shape_keys(None)

    mock_obj = MagicMock()
    mock_kb = MagicMock()
    mock_kb.value = 0.8
    mock_obj.data.shape_keys.key_blocks = [mock_kb]

    MeshDecimator.reset_shape_keys_to_basis(mock_obj)
    assert mock_kb.value == 0.0


def test_temporary_vertex_group_context_manager():
    from core.decimator import temporary_vertex_group

    mock_obj = MagicMock()
    mock_vg = MagicMock()
    mock_obj.vertex_groups.get.return_value = mock_vg

    with temporary_vertex_group(mock_obj, "TestGroup"):
        pass

    mock_obj.vertex_groups.remove.assert_called_once_with(mock_vg)

    # Test exception safety
    mock_obj.vertex_groups.reset_mock()
    try:
        with temporary_vertex_group(mock_obj, "TestGroup"):
            raise ValueError("Test error inside context")
    except ValueError:
        pass

    mock_obj.vertex_groups.remove.assert_called_once_with(mock_vg)


def test_lod_generator_graceful_handling(monkeypatch):
    """Verify generate_all_lods handles None/empty context and objects defensively."""
    from tests.conftest import MockBlendData

    bdata = MockBlendData()
    success, msg = generate_all_lods(context=None, props=None, mesh_objs=[], blend_data=bdata)
    assert success is True  # Blender context not available in headless test mock
    assert "not available" in msg.lower()

    # Verify handling with empty mesh list when bpy is present
    monkeypatch.setattr("core.lod_generator.bpy", MagicMock())
    mock_ctx = MagicMock()
    mock_props = MagicMock()
    mock_props.lods = []
    success, msg = generate_all_lods(context=mock_ctx, props=mock_props, mesh_objs=[], blend_data=bdata)
    assert success is False
    assert "no mesh objects" in msg.lower()


def test_lod_generator_exception_rollback_and_pose_restoration(monkeypatch):
    """Verify generate_all_lods restores armature pose_position and returns failure cleanly on error."""
    from tests.conftest import MockBlendData

    monkeypatch.setattr("core.lod_generator.bpy", MagicMock())
    monkeypatch.setattr(
        "core.lod_generator.CollectionCloneDAG.wrap_loose_objects_into_root_collection",
        MagicMock(side_effect=RuntimeError("Simulated DAG failure")),
    )

    mock_ctx = MagicMock()
    mock_ctx.collection = None
    mock_props = MagicMock()
    mock_tier = MagicMock()
    mock_tier.screen_size_pct = 50.0
    mock_props.lods = [mock_tier]

    mock_armature = MagicMock()
    mock_armature.type = "ARMATURE"
    mock_armature.data.pose_position = "POSE"

    broken_obj = MagicMock()
    broken_obj.name = "SM_Broken"
    broken_obj.type = "MESH"
    broken_obj.data = None
    broken_obj.users_collection = []

    success, msg = generate_all_lods(
        context=mock_ctx,
        props=mock_props,
        mesh_objs=[broken_obj],
        armature_obj=mock_armature,
        blend_data=MockBlendData(),
    )
    # Must fail safely without uncaught exception and restore pose_position
    assert success is False
    assert "simulated dag failure" in msg.lower()
    assert mock_armature.data.pose_position == "POSE"


def test_execute_decimate_qem_raises_decimation_error_on_apply_failure(monkeypatch):
    """Verify execute_decimate_qem fails fast and raises DecimationError when modifier apply fails."""
    import pytest
    from core.exceptions import DecimationError

    mock_bpy = MagicMock()
    monkeypatch.setattr("core.decimator.bpy", mock_bpy)

    mock_obj = MagicMock()
    mock_obj.name = "SM_Hero"
    mock_obj.type = "MESH"
    mock_obj.data.users = 1
    mock_mod = MagicMock()
    mock_mod.name = "OmniMesh_Decimate"
    mock_modifiers = MagicMock()
    mock_modifiers.new.return_value = mock_mod
    mock_modifiers.__contains__.return_value = True
    mock_obj.modifiers = mock_modifiers

    # Simulate Blender modifier apply raising RuntimeError
    mock_bpy.ops.object.modifier_apply.side_effect = RuntimeError("Context incorrect for modifier apply")

    with pytest.raises(DecimationError) as exc_info:
        MeshDecimator.execute_decimate_qem(mock_obj, 0.5)

    assert "Context incorrect for modifier apply" in str(exc_info.value)
    assert "SM_Hero" in str(exc_info.value)
    # Ensure broken modifier was removed
    mock_obj.modifiers.remove.assert_called_with(mock_mod)


def test_lod_generator_pure_di_with_mock_blend_data(monkeypatch):
    """Verify generate_all_lods accepts injected BlendData without global bpy.data."""
    from tests.conftest import MockBlendData

    monkeypatch.setattr("core.lod_generator.bpy", MagicMock())
    bdata = MockBlendData()
    mock_ctx = MagicMock()
    mock_ctx.blend_data = bdata

    # Empty meshes -> fails safely with expected error message
    success, msg = generate_all_lods(context=mock_ctx, props=None, mesh_objs=[], blend_data=bdata)
    assert success is False
    assert "no mesh objects" in msg.lower()
