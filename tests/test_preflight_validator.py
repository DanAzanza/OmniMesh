"""
Unit tests for PreFlightValidator quality gates.
"""

from exporters.engine_export import PreFlightValidator


class MockVector:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = x
        self.y = y
        self.z = z

    @property
    def translation(self):
        return self

    def __sub__(self, other):
        return MockVector(self.x - other.x, self.y - other.y, self.z - other.z)

    @property
    def length(self):
        return (self.x**2 + self.y**2 + self.z**2) ** 0.5


class MockScale:
    def __init__(self, x=1.0, y=1.0, z=1.0):
        self.x = x
        self.y = y
        self.z = z

    def __iter__(self):
        return iter((self.x, self.y, self.z))


class MockMaterialSlot:
    def __init__(self, material="Mat"):
        self.material = material


class MockMeshData:
    def __init__(self, poly_count=100):
        self.polygons = [object()] * poly_count


class MockObject:
    def __init__(self, name="SM_Obj", translation=(0, 0, 0), scale=(1, 1, 1), polys=100, mat_slots=1):
        self.name = name
        self.type = "MESH"
        self.matrix_world = MockVector(*translation)
        self.scale = MockScale(*scale)
        self.data = MockMeshData(polys)
        self.material_slots = [MockMaterialSlot(f"Mat_{i}") for i in range(mat_slots)]


class MockLODTier:
    def __init__(self, obj=None):
        self.generated_obj = obj


class MockLODToolProps:
    def __init__(self, lod_count=3, export_dir="//Export/"):
        self.lods = []
        self.export_directory = export_dir
        self.target_engine = "MSFS_2024"
        self.export_base_name = "SM_Test"


class MockContext:
    def __init__(self, props=None):
        self.scene = type("Scene", (), {"lod_tool": props or MockLODToolProps()})()


def test_validator_no_context():
    errors = PreFlightValidator.run_checks(None)
    assert len(errors) == 1
    assert "not available" in errors[0]


def test_validator_no_lods_configured():
    props = MockLODToolProps()
    props.lods = []
    ctx = MockContext(props)
    errors = PreFlightValidator.run_checks(ctx)
    assert len(errors) == 1
    assert "No LOD tiers configured" in errors[0]


def test_validator_ungenerated_tiers():
    props = MockLODToolProps()
    props.lods = [MockLODTier(None), MockLODTier(None)]
    ctx = MockContext(props)
    errors = PreFlightValidator.run_checks(ctx)
    assert any("not been generated yet" in e for e in errors)


def test_validator_origin_mismatch():
    obj0 = MockObject("LOD0", translation=(0, 0, 0))
    obj1 = MockObject("LOD1", translation=(0, 2.5, 0))
    props = MockLODToolProps()
    props.lods = [MockLODTier(obj0), MockLODTier(obj1)]
    ctx = MockContext(props)
    errors = PreFlightValidator.run_checks(ctx)
    assert any("origin does not match" in e for e in errors)


def test_validator_unapplied_scale():
    obj0 = MockObject("LOD0", scale=(1.0, 1.0, 1.0))
    obj1 = MockObject("LOD1", scale=(1.0, 1.5, 1.0))
    props = MockLODToolProps()
    props.lods = [MockLODTier(obj0), MockLODTier(obj1)]
    ctx = MockContext(props)
    errors = PreFlightValidator.run_checks(ctx)
    assert any("unapplied scale" in e for e in errors)


def test_validator_empty_geometry():
    obj0 = MockObject("LOD0", polys=500)
    obj1 = MockObject("LOD1", polys=0)
    props = MockLODToolProps()
    props.lods = [MockLODTier(obj0), MockLODTier(obj1)]
    ctx = MockContext(props)
    errors = PreFlightValidator.run_checks(ctx)
    assert any("0 polygons" in e for e in errors)


def test_validator_unassigned_material():
    obj0 = MockObject("LOD0", mat_slots=1)
    obj1 = MockObject("LOD1", mat_slots=1)
    obj1.material_slots[0].material = None
    props = MockLODToolProps()
    props.lods = [MockLODTier(obj0), MockLODTier(obj1)]
    ctx = MockContext(props)
    errors = PreFlightValidator.run_checks(ctx)
    assert any("unassigned material" in e for e in errors)


def test_validator_empty_export_directory():
    obj0 = MockObject("LOD0")
    obj1 = MockObject("LOD1")
    props = MockLODToolProps(export_dir="")
    props.lods = [MockLODTier(obj0), MockLODTier(obj1)]
    ctx = MockContext(props)
    errors = PreFlightValidator.run_checks(ctx)
    assert any("Export directory path is empty" in e for e in errors)


def test_validator_all_checks_pass():
    obj0 = MockObject("LOD0", translation=(0, 0, 0), scale=(1, 1, 1), polys=1000, mat_slots=2)
    obj1 = MockObject("LOD1", translation=(0, 0, 0), scale=(1, 1, 1), polys=500, mat_slots=2)
    obj2 = MockObject("LOD2", translation=(0, 0, 0), scale=(1, 1, 1), polys=250, mat_slots=2)
    props = MockLODToolProps(export_dir="//Export/")
    props.lods = [MockLODTier(obj0), MockLODTier(obj1), MockLODTier(obj2)]
    ctx = MockContext(props)
    errors = PreFlightValidator.run_checks(ctx)
    assert len(errors) == 0
