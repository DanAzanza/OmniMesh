from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from core.pivot import PivotPreservationEngine
from exporters.msfs_export import MSFSExporter


class DummyObject:
    def __init__(self, name: str, obj_type: str = "EMPTY", is_pivot: bool = False, is_socket: bool = False):
        self.name = name
        self.type = obj_type
        self.matrix_world = MagicMock()
        self.data = MagicMock() if obj_type == "MESH" else None
        self._custom_props = {"is_pivot": is_pivot, "is_socket": is_socket}

    def get(self, key: str, default: Any = None) -> Any:
        return self._custom_props.get(key, default)


class DummyCollection:
    def __init__(self, name: str, objects: list[DummyObject]):
        self.name = name
        self.objects = objects
        self.all_objects = objects


def test_identify_pivots_and_sockets():
    pivot_obj = DummyObject("Pivot", "EMPTY", is_pivot=True)
    sock_light = DummyObject("SOCKET_NavLight_L", "EMPTY", is_socket=True)
    sock_gear = DummyObject("MOUNT_Gear_L", "EMPTY")
    mesh_hull = DummyObject("Fuselage", "MESH")
    arm_rig = DummyObject("Character_Rig", "ARMATURE")
    col_hull = DummyObject("UCX_Fuselage_01", "MESH")
    col_hull._custom_props["_is_collider"] = True

    coll = DummyCollection("Model", [pivot_obj, sock_light, sock_gear, mesh_hull, arm_rig, col_hull])

    found_pivot, sockets, meshes, armatures = PivotPreservationEngine.identify_pivots_and_sockets(coll)

    assert found_pivot == pivot_obj
    assert len(sockets) == 2
    assert sock_light in sockets
    assert sock_gear in sockets
    assert len(meshes) == 1
    assert mesh_hull in meshes
    assert len(armatures) == 1
    assert arm_rig in armatures


def test_identify_pivots_null_and_empty():
    p, s, m, a = PivotPreservationEngine.identify_pivots_and_sockets(None)
    assert p is None
    assert s == []
    assert m == []
    assert a == []


def test_msfs_descending_minsize_xml():
    tiers = [
        {"screen_size_pct": 100.0},
        {"screen_size_pct": 50.0},
        {"screen_size_pct": 25.0},
        {"screen_size_pct": 10.0},
    ]

    xml = MSFSExporter.generate_model_info_xml("Cessna", tiers)

    # LOD0 should have minSize="50" (the screen percentage of LOD1)
    assert 'minSize="50" ModelFile="Cessna_LOD0.gltf"' in xml
    # LOD1 should have minSize="25" (the screen percentage of LOD2)
    assert 'minSize="25" ModelFile="Cessna_LOD1.gltf"' in xml
    # LOD2 should have minSize="10" (the screen percentage of LOD3)
    assert 'minSize="10" ModelFile="Cessna_LOD2.gltf"' in xml
    # LOD3 (final tier) MUST have minSize="0"
    assert 'minSize="0" ModelFile="Cessna_LOD3.gltf"' in xml


def test_msfs_model_info_xml_single_or_empty():
    xml_single = MSFSExporter.generate_model_info_xml("Prop", [{"screen_size_pct": 100.0}])
    assert (
        'minSize="0" ModelFile="Prop_LOD0.gltf"' in xml_single
        or 'minSize="0.0" ModelFile="Prop_LOD0.gltf"' in xml_single
    )

    xml_empty = MSFSExporter.generate_model_info_xml("Empty", [])
    assert 'minSize="0" ModelFile="Empty_LOD0.gltf"' in xml_empty


def test_get_relative_matrix_null_safety():
    assert PivotPreservationEngine.get_relative_matrix(None, None) is not None
    dummy = DummyObject("Test", "MESH")
    dummy.matrix_world = None
    assert PivotPreservationEngine.get_relative_matrix(dummy, None) is not None
