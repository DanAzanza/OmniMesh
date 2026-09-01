"""
Unit tests for OmniMesh Material Optimization Module.
"""

from __future__ import annotations

import pytest

from core.materials import MaterialOptimizer


class DummyPolygon:
    def __init__(self, material_index: int, area: float):
        self.material_index = material_index
        self.area = area


class DummyMaterial:
    def __init__(self, name: str):
        self.name = name


class DummyMaterialSlot:
    def __init__(self, material: DummyMaterial | None = None):
        self.material = material


class DummyMeshData:
    def __init__(self, polygons: list[DummyPolygon]):
        self.polygons = polygons


class DummyMeshObject:
    def __init__(self, material_slots: list[DummyMaterialSlot], polygons: list[DummyPolygon]):
        self.type = "MESH"
        self.material_slots = material_slots
        self.data = DummyMeshData(polygons)
        self.active_material_index = 0


def test_calculate_material_areas():
    slots = [DummyMaterialSlot(DummyMaterial("Mat0")), DummyMaterialSlot(DummyMaterial("Mat1"))]
    polys = [
        DummyPolygon(0, 10.0),
        DummyPolygon(0, 5.0),
        DummyPolygon(1, 2.5),
        DummyPolygon(1, 3.5),
    ]
    obj = DummyMeshObject(slots, polys)

    areas = MaterialOptimizer.calculate_material_areas(obj)
    assert areas[0] == pytest.approx(15.0)
    assert areas[1] == pytest.approx(6.0)


def test_calculate_material_areas_empty_or_null():
    assert MaterialOptimizer.calculate_material_areas(None) == {}

    obj_no_slots = DummyMeshObject([], [DummyPolygon(0, 5.0)])
    assert MaterialOptimizer.calculate_material_areas(obj_no_slots) == {}


def test_get_dominant_material_index():
    areas = {0: 12.5, 1: 45.2, 2: 3.1}
    assert MaterialOptimizer.get_dominant_material_index(areas) == 1

    # Empty dict fallback
    assert MaterialOptimizer.get_dominant_material_index({}) == 0


def test_consolidate_micro_materials_null_and_empty():
    res = MaterialOptimizer.consolidate_micro_materials(None, area_crit=0.1)
    assert res["consolidated_slots"] == 0
    assert res["faces_reassigned"] == 0

    obj_single_slot = DummyMeshObject([DummyMaterialSlot()], [DummyPolygon(0, 1.0)])
    res_single = MaterialOptimizer.consolidate_micro_materials(obj_single_slot, area_crit=0.1)
    assert res_single["consolidated_slots"] == 0


def test_purge_unused_materials_null():
    assert MaterialOptimizer.purge_unused_materials(None) == 0
