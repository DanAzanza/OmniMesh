"""
Unit tests for MSFSMaterialAnalyzer and MaterialProfile.
"""

from core.material_analyzer import MSFSMaterialAnalyzer, MSFSMaterialKind


class MockMaterial:
    def __init__(self, name: str, custom_props: dict | None = None):
        self.name = name
        self._props = custom_props or {}

    def get(self, key, default=None):
        return self._props.get(key, default)


class MockMeshObject:
    def __init__(self, name: str, materials: list[MockMaterial]):
        self.name = name
        self.type = "MESH"
        self.material_slots = [type("Slot", (), {"material": m})() for m in materials]


def test_classify_by_asobo_type_id():
    mat_decal = MockMaterial("MyMat", {"msfs_material_type": 2})
    profile_decal = MSFSMaterialAnalyzer.classify_material(mat_decal)
    assert profile_decal.kind == MSFSMaterialKind.DECAL
    assert profile_decal.requires_planar_protection is True

    mat_windshield = MockMaterial("MyGlass", {"msfs_material_type": 4})
    profile_glass = MSFSMaterialAnalyzer.classify_material(mat_windshield)
    assert profile_glass.kind == MSFSMaterialKind.WINDSHIELD
    assert profile_glass.requires_boundary_protection is True

    mat_invisible = MockMaterial("ClickSpot", {"msfs_material_type": 12})
    profile_inv = MSFSMaterialAnalyzer.classify_material(mat_invisible)
    assert profile_inv.kind == MSFSMaterialKind.INVISIBLE


def test_classify_by_name_heuristic():
    mat_rivet = MockMaterial("Decals_Rivet_02")
    profile_rivet = MSFSMaterialAnalyzer.classify_material(mat_rivet)
    assert profile_rivet.kind == MSFSMaterialKind.DECAL

    mat_prop = MockMaterial("Propeller_Blur")
    profile_prop = MSFSMaterialAnalyzer.classify_material(mat_prop)
    assert profile_prop.kind == MSFSMaterialKind.PROPELLER


def test_analyze_mesh_object():
    obj = MockMeshObject("x0_Windshield", [MockMaterial("Windshield_Mat", {"msfs_material_type": 4})])
    assert MSFSMaterialAnalyzer.is_windshield_mesh(obj) is True
    assert MSFSMaterialAnalyzer.is_decal_mesh(obj) is False
