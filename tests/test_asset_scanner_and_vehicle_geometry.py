"""Unit and boundary tests for core.asset_scanner and core.vehicle_geometry."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from core import asset_scanner
from core.vehicle_geometry import (
    collect_airframe_vertices,
    detect_airframe_extrema,
    detect_ground_vehicle_extrema,
    detect_wheel_submeshes,
    extract_world_vertices_numpy,
)


class _FakeVerts:
    def __init__(self, coords: list[tuple[float, float, float]]) -> None:
        self._arr = np.array(coords, dtype=np.float32)

    def __len__(self) -> int:
        return int(self._arr.shape[0])

    def foreach_get(self, attr: str, out: np.ndarray) -> None:
        assert attr == "co"
        out[:] = self._arr.reshape(-1)


class _FakeCollection:
    def __init__(
        self,
        name: str,
        objects: list[object] | None = None,
        children: list[_FakeCollection] | None = None,
        props: dict[str, object] | None = None,
        *,
        no_all_objects: bool = False,
    ) -> None:
        self.name = name
        self.objects = list(objects or [])
        self.children = list(children or [])
        self._props = dict(props or {})
        self._no_all_objects = no_all_objects

    def get(self, key: str, default: object = None) -> object:
        return self._props.get(key, default)

    @property
    def all_objects(self) -> list[object]:
        if self._no_all_objects:
            raise AttributeError("no all_objects")
        result = list(self.objects)
        for child in self.children:
            result.extend(child.all_objects)
        return result


class _FakeMeshObj:
    def __init__(
        self,
        name: str,
        coords: list[tuple[float, float, float]],
        *,
        obj_type: str = "MESH",
        props: dict[str, object] | None = None,
        bound_box: list[tuple[float, float, float]] | None = None,
    ) -> None:
        self.name = name
        self.type = obj_type
        self.data = (
            SimpleNamespace(
                vertices=_FakeVerts(coords),
                loops=[None] * (3 * max(1, len(coords) // 3)),
                polygons=[None] * max(1, len(coords) // 3),
            )
            if obj_type == "MESH"
            else None
        )
        self.matrix_world = np.eye(4, dtype=np.float32)
        self.material_slots = [object()]
        self.users_collection: list[object] = []
        self._props = dict(props or {})
        self.bound_box = bound_box

    def get(self, key: str, default: object = None) -> object:
        return self._props.get(key, default)


def test_asset_scanner_missing_context_and_tree_traversal() -> None:
    """Verify get_available_asset_names guards and recursive scene.collection fallback."""
    with patch.object(asset_scanner, "bpy", None):
        assert asset_scanner.get_available_asset_names(None, blend_data=MagicMock()) == []

    fake_bpy = MagicMock()
    ctx_no_scene: Any = SimpleNamespace(scene=None)
    with patch.object(asset_scanner, "bpy", fake_bpy):
        assert asset_scanner.get_available_asset_names(ctx_no_scene, blend_data=MagicMock()) == []

    fuselage = _FakeMeshObj("DA62_Fuselage", [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
    lod0_coll = _FakeCollection("DA62_LOD0", objects=[fuselage], no_all_objects=True)
    hidden_coll = _FakeCollection(".Hidden", objects=[fuselage])
    lod1_coll = _FakeCollection("DA62_LOD1", objects=[fuselage])
    config_coll = _FakeCollection("DA62_Meta", objects=[fuselage], props={"_omnimesh_role": "CONFIG"})
    scene_root = _FakeCollection("Scene Collection", children=[lod0_coll, hidden_coll, lod1_coll, config_coll])
    scene = SimpleNamespace(collection=scene_root)
    ctx: Any = SimpleNamespace(scene=scene, view_layer=None, active_object=None, selected_objects=[])

    # Fallback recursive scene.collection walk when blend_data=None
    with patch.object(asset_scanner, "bpy", fake_bpy):
        assert asset_scanner.get_available_asset_names(ctx, blend_data=None) == ["DA62"]  # type: ignore[arg-type]


def test_asset_scanner_resolve_name_base_meshes_and_scan_state() -> None:
    """Verify asset resolution, base mesh filtering, and multi-tier state scan."""
    fake_bpy = MagicMock()
    body = _FakeMeshObj("Plane_Body", [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
    col_mesh = _FakeMeshObj("Plane_Collider_Wing", [(0, 0, 0)], props={"_is_collider": True})
    ucx_mesh = _FakeMeshObj("UCX_Plane_Body", [(0, 0, 0)])
    lod2_mesh = _FakeMeshObj("Plane_LOD2", [(0, 0, 0)])
    empty_obj = _FakeMeshObj("Plane_Empty", [], obj_type="EMPTY")

    c_lod0 = _FakeCollection(
        "Plane_LOD0", objects=[body, col_mesh, ucx_mesh, lod2_mesh, empty_obj], no_all_objects=True
    )
    body.users_collection = [c_lod0]
    c_lod1 = _FakeCollection("Plane_LOD1", objects=[_FakeMeshObj("Plane_LOD1_Mesh", [(0, 0, 0), (1, 0, 0), (0, 1, 0)])])
    c_imp = _FakeCollection(
        "Plane_LOD_Impostor", objects=[_FakeMeshObj("Plane_IMP", [(0, 0, 0), (1, 0, 0), (0, 1, 0)])]
    )

    col_map = {c.name: c for c in (c_lod0, c_lod1, c_imp)}
    bdata: Any = SimpleNamespace(collections=MagicMock(get=col_map.get, __iter__=lambda s: iter(col_map.values())))
    # Make blend_data.collections iterable with list behavior
    bdata.collections = _CollDict(col_map)

    scene_root = _FakeCollection("Scene Collection", children=[c_lod0, c_lod1, c_imp])
    active_lc = SimpleNamespace(collection=c_lod1)
    ctx: Any = SimpleNamespace(
        scene=SimpleNamespace(collection=scene_root),
        view_layer=SimpleNamespace(active_layer_collection=active_lc),
        active_object=body,
        selected_objects=[body],
    )

    with patch.object(asset_scanner, "bpy", fake_bpy):
        # 1. Explicit active_asset property
        assert (
            asset_scanner.resolve_effective_asset_name(
                ctx, SimpleNamespace(active_asset="CustomAsset"), blend_data=bdata
            )
            == "CustomAsset"
        )
        # 2. Active layer collection resolution (strips _LOD1)
        assert (
            asset_scanner.resolve_effective_asset_name(ctx, SimpleNamespace(active_asset="AUTO"), blend_data=bdata)
            == "Plane"
        )
        # 3. Active object users_collection resolution when no active_layer_collection
        ctx.view_layer = None
        assert asset_scanner.resolve_effective_asset_name(ctx, None, blend_data=bdata) == "Plane"
        # 4. Available list fallback and finally 'Asset'
        ctx.active_object = None
        assert asset_scanner.resolve_effective_asset_name(ctx, None, blend_data=bdata) == "Plane"
        empty_bdata: Any = SimpleNamespace(collections=_CollDict({}))
        assert asset_scanner.resolve_effective_asset_name(ctx, None, blend_data=empty_bdata) == "Asset"

        # Missing collection fallback in get_asset_collection and get_asset_base_meshes
        assert asset_scanner.get_asset_collection(ctx, "Plane", blend_data=None) == c_lod0  # type: ignore[arg-type]
        ctx.selected_objects = []
        ctx.active_object = body
        assert asset_scanner.get_asset_base_meshes(ctx, "UnknownAsset", blend_data=empty_bdata) == [body]

        state = asset_scanner.scan_asset_state(ctx, "Plane", blend_data=bdata)
        assert state["base_meshes"] == [body]
        assert 0 in state["existing_tiers"]
        assert 1 in state["existing_tiers"]
        assert -1 in state["existing_tiers"]
        assert state["existing_tiers"][-1]["is_impostor"] is True


class _CollDict(dict):
    def __iter__(self):
        return iter(self.values())


def test_vehicle_geometry_vertex_extraction_and_depsgraph_cleanup() -> None:
    """Verify extract_world_vertices_numpy sequence mode, empty guards, and to_mesh_clear."""
    assert extract_world_vertices_numpy(None).shape == (0, 3)  # type: ignore[arg-type]
    assert extract_world_vertices_numpy(_FakeMeshObj("Empty", [], obj_type="EMPTY")).shape == (0, 3)  # type: ignore[arg-type]
    assert extract_world_vertices_numpy(_FakeMeshObj("NoVerts", [])).shape == (0, 3)  # type: ignore[arg-type]

    m1 = _FakeMeshObj("Fuselage", [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
    m_antenna = _FakeMeshObj("Antenna_VHF", [(10.0, 10.0, 10.0), (10.0, 10.0, 11.0), (10.0, 10.0, 12.0)])
    seq_pts = extract_world_vertices_numpy([m1, m_antenna])  # type: ignore[arg-type]
    assert seq_pts.shape == (6, 3)

    filtered = collect_airframe_vertices([m1, m_antenna], filter_non_structural=True)  # type: ignore[arg-type]
    assert filtered.shape == (3, 3)
    assert collect_airframe_vertices([m_antenna], filter_non_structural=True).shape == (0, 3)  # type: ignore[arg-type]

    # Depsgraph path must call to_mesh_clear even if extraction raises
    eval_mesh = SimpleNamespace(vertices=_FakeVerts([(1.0, 2.0, 3.0)]))
    eval_obj = MagicMock()
    eval_obj.to_mesh.return_value = eval_mesh
    eval_obj.matrix_world = np.eye(4, dtype=np.float32)
    obj = MagicMock()
    obj.type = "MESH"
    obj.data = True
    obj.evaluated_get.return_value = eval_obj

    pts = extract_world_vertices_numpy(obj, depsgraph=MagicMock())
    assert pts.shape == (1, 3)
    eval_obj.to_mesh_clear.assert_called_once()


def test_vehicle_geometry_wheels_ground_and_negative_extrema() -> None:
    """Verify detect_wheel_submeshes heuristics, bound_box fallback, ground extrema, and guards."""
    with pytest.raises(ValueError, match="Insufficient vertices"):
        detect_airframe_extrema(np.zeros((2, 3), dtype=np.float32))
    with pytest.raises(ValueError, match="Insufficient vertices"):
        detect_ground_vehicle_extrema(np.zeros((3, 3), dtype=np.float32))

    # Ground vehicle extrema
    ground_pts = np.array(
        [[-1.0, 2.0, 0.0], [1.0, 2.0, 0.0], [-1.0, -2.0, 0.0], [1.0, -2.0, 1.6]],
        dtype=np.float32,
    )
    ground_ext = detect_ground_vehicle_extrema(ground_pts)
    assert ground_ext["Scrape_Roof"][2] == pytest.approx(1.6)
    assert ground_ext["Scrape_Bumper_F_L"][0] == pytest.approx(-1.0)
    assert ground_ext["Scrape_Bumper_R_R"][1] == pytest.approx(-2.0)

    # Offset fuselage triggering centerline_verts < 4 fallback in detect_airframe_extrema
    offset_pts = np.array(
        [[5.0, 4.0, 0.0], [6.0, -3.0, 1.0], [5.5, 0.0, -1.0], [7.0, 1.0, 2.0]],
        dtype=np.float32,
    )
    offset_ext = detect_airframe_extrema(offset_pts, fuselage_width_tol_m=0.1)
    assert offset_ext["Scrape_Nose"][1] == pytest.approx(4.0)

    assert detect_wheel_submeshes([]) == {}

    wheel_objs = [
        _FakeMeshObj("Tire_Nose", [(0.0, 2.0, 0.0), (0.2, 2.2, 0.5), (-0.2, 1.8, -0.3)]),
        _FakeMeshObj("Tire_Tail", [(0.0, -3.0, 0.0), (0.1, -2.9, 0.2), (-0.1, -3.1, -0.1)]),
        _FakeMeshObj("Wheel_Front_Left", [(-1.0, 1.5, 0.0), (-0.8, 1.6, 0.3), (-1.2, 1.4, -0.2)]),
        _FakeMeshObj("Wheel_Front_Right", [(1.0, 1.5, 0.0), (1.2, 1.6, 0.3), (0.8, 1.4, -0.2)]),
        _FakeMeshObj("Wheel_Rear_Left", [(-1.1, -1.5, 0.0), (-0.9, -1.4, 0.3), (-1.2, -1.6, -0.2)]),
        _FakeMeshObj("Wheel_Rear_Right", [(1.1, -1.5, 0.0), (1.2, -1.4, 0.3), (0.9, -1.6, -0.2)]),
        _FakeMeshObj("Wheel_Center_Unnamed", [], bound_box=[(-0.1, 0.9, -0.5), (0.1, 1.1, 0.1)]),
        _FakeMeshObj("Door_Lever", [(0, 0, 0), (1, 0, 0), (0, 1, 0)]),  # excluded by pattern
        _FakeMeshObj("Wheel_Broken_BBox", [], bound_box=cast(Any, [("bad",)])),  # triggers bound_box error log cleanly
    ]
    # Note: fake _FakeMeshObj with matrix_world ndarray requires a mock matrix multiplication for bound_box
    with patch("core.vehicle_geometry.Vector", side_effect=lambda x: x):
        wheel_objs[-3].matrix_world = MagicMock()
        wheel_objs[-3].matrix_world.__matmul__.side_effect = lambda pt: pt
        wheel_objs[-1].matrix_world = MagicMock()
        wheel_objs[-1].matrix_world.__matmul__.side_effect = TypeError("bad pt")
        detected = detect_wheel_submeshes(wheel_objs)  # type: ignore[arg-type]

    assert "WHEEL_NOSE" in detected
    assert "WHEEL_TAIL" in detected
    assert "WHEEL_FRONT_L" in detected
    assert "WHEEL_FRONT_R" in detected
    assert "WHEEL_REAR_L" in detected
    assert "WHEEL_REAR_R" in detected
