"""
Unit tests for Collection-First Architecture (Variante A) across all OmniMesh engine exporters.
Verifies strict exclusion of technical subcollections (_Spatial, _Lights, _Cameras),
support for multi-model packages (exterior, interior, variants), and transactional scene-graph rollback.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock

import pytest

from exporters.engine_export import AssetMeshResolver
from exporters.godot_export import GodotExporter
from exporters.msfs_export import MSFSExporter
from exporters.ue5_export import UE5Exporter
from exporters.unity_export import UnityExporter


class MockVector:
    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0):
        self.x = x
        self.y = y
        self.z = z

    @property
    def translation(self) -> MockVector:
        return self

    def __sub__(self, other: Any) -> MockVector:
        return MockVector(
            self.x - getattr(other, "x", 0.0),
            self.y - getattr(other, "y", 0.0),
            self.z - getattr(other, "z", 0.0),
        )

    @property
    def length(self) -> float:
        return (self.x**2 + self.y**2 + self.z**2) ** 0.5


class MockScale:
    def __init__(self, x: float = 1.0, y: float = 1.0, z: float = 1.0):
        self.x = x
        self.y = y
        self.z = z

    def __iter__(self):
        return iter((self.x, self.y, self.z))


class MockObject:
    def __init__(
        self,
        name: str,
        obj_type: str = "MESH",
        translation: tuple[float, float, float] = (0.0, 0.0, 0.0),
        parent: Any = None,
    ):
        self.name = name
        self.type = obj_type
        self.matrix_world = MockVector(*translation)
        self.scale = MockScale(1.0, 1.0, 1.0)
        self.parent = parent
        self.users_collection: list[Any] = []
        self.material_slots: list[Any] = []
        self.data = type("MeshData", (), {"polygons": [1, 2, 3]})()
        self.modifiers: list[Any] = []
        self.hide_viewport = False
        self.select = False
        self._custom_props: dict[str, Any] = {}

    def select_set(self, state: bool) -> None:
        self.select = state

    def hide_set(self, state: bool, view_layer: Any = None) -> None:
        self.hide_viewport = state

    def __getitem__(self, key: str) -> Any:
        return self._custom_props[key]

    def __setitem__(self, key: str, val: Any) -> None:
        self._custom_props[key] = val

    def __delitem__(self, key: str) -> None:
        del self._custom_props[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._custom_props.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self._custom_props


class MockCollectionChildren:
    def __init__(self, owner: MockCollection):
        self._owner = owner

    def get(self, name: str, default: Any = None) -> Any:
        for c in self._owner.children_list:
            if c.name == name:
                return c
        return default

    def __iter__(self):
        return iter(self._owner.children_list)

    def __contains__(self, item: Any) -> bool:
        name = item.name if hasattr(item, "name") else str(item)
        return any(c.name == name for c in self._owner.children_list)

    def link(self, child: MockCollection) -> None:
        self._owner.add_child(child)

    def unlink(self, child: MockCollection) -> None:
        if child in self._owner.children_list:
            self._owner.children_list.remove(child)


class MockCollectionObjects:
    def __init__(self, owner: MockCollection):
        self._owner = owner

    def link(self, obj: MockObject) -> None:
        self._owner.add_object(obj)

    def unlink(self, obj: MockObject) -> None:
        if obj in self._owner._objects_list:
            self._owner._objects_list.remove(obj)
            if self._owner in obj.users_collection:
                obj.users_collection.remove(self._owner)

    def __iter__(self):
        return iter(self._owner._objects_list)

    def __len__(self):
        return len(self._owner._objects_list)

    def __contains__(self, item: Any) -> bool:
        name = item.name if hasattr(item, "name") else str(item)
        return any(o.name == name for o in self._owner._objects_list)

    def __getitem__(self, idx: int) -> MockObject:
        return self._owner._objects_list[idx]


class MockCollection:
    def __init__(self, name: str):
        self.name = name
        self._objects_list: list[MockObject] = []
        self.objects = MockCollectionObjects(self)
        self.children_list: list[MockCollection] = []
        self.children = MockCollectionChildren(self)
        self._custom_props: dict[str, Any] = {}

    def __getitem__(self, key: str) -> Any:
        return self._custom_props[key]

    def __setitem__(self, key: str, val: Any) -> None:
        self._custom_props[key] = val

    def get(self, key: str, default: Any = None) -> Any:
        return self._custom_props.get(key, default)

    @property
    def all_objects(self) -> list[MockObject]:
        objs = list(self._objects_list)
        for c in self.children_list:
            objs.extend(c.all_objects)
        return objs

    def add_object(self, obj: MockObject) -> None:
        if obj not in self._objects_list:
            self._objects_list.append(obj)
            obj.users_collection.append(self)

    def add_child(self, child: MockCollection) -> None:
        if child not in self.children_list:
            self.children_list.append(child)


class MockDataObjects:
    def __init__(self, objects: list[MockObject]):
        self._objects = list(objects)

    def __iter__(self):
        return iter(self._objects)

    def __len__(self):
        return len(self._objects)

    def __contains__(self, item: Any) -> bool:
        if isinstance(item, str):
            return any(o.name == item for o in self._objects)
        return item in self._objects

    def get(self, name: str, default: Any = None) -> Any:
        for o in self._objects:
            if o.name == name:
                return o
        return default

    def remove(self, obj: Any, do_unlink: bool = True) -> None:
        if obj in self._objects:
            self._objects.remove(obj)

    def new(self, name: str, object_data: Any = None) -> MockObject:
        obj = MockObject(name, obj_type="EMPTY" if object_data is None else "MESH")
        self._objects.append(obj)
        return obj


@pytest.fixture
def mock_hierarchy():
    """Sets up a complete Variante A mock collection hierarchy."""
    cols: dict[str, MockCollection] = {}

    def create_col(name: str) -> MockCollection:
        col = MockCollection(name)
        cols[name] = col
        return col

    root = create_col("Simple_Aircraft")
    config = create_col("Simple_Aircraft_Config")
    lod0 = create_col("Simple_Aircraft_LOD0")
    spatial = create_col("Simple_Aircraft_Spatial")
    lights = create_col("Simple_Aircraft_Lights")
    cameras = create_col("Simple_Aircraft_Cameras")
    lod1 = create_col("Simple_Aircraft_LOD1")
    colliders = create_col("Simple_Aircraft_Colliders")
    impostors = create_col("Simple_Aircraft_LOD_Impostor")

    root.add_child(config)
    root.add_child(lod0)
    root.add_child(lod1)
    root.add_child(colliders)
    root.add_child(impostors)

    config.add_child(spatial)
    config.add_child(lights)
    config.add_child(cameras)

    # Add objects
    f_lod0 = MockObject("Fuselage_LOD0", "MESH")
    w_lod0 = MockObject("Wing_LOD0", "MESH")
    lod0.add_object(f_lod0)
    lod0.add_object(w_lod0)

    # Technical objects
    datum = MockObject("MSFS_Datum", "EMPTY")
    spatial.add_object(datum)

    nav_light = MockObject("Light_Nav_Left", "LIGHT")
    lights.add_object(nav_light)

    cam = MockObject("Eyepoint", "CAMERA")
    cameras.add_object(cam)

    f_lod1 = MockObject("Fuselage_LOD1", "MESH")
    lod1.add_object(f_lod1)

    coll = MockObject("Fuselage_Collider", "MESH")
    coll["_is_collider"] = True
    colliders.add_object(coll)

    imp = MockObject("Fuselage_Impostor", "MESH")
    imp["_is_impostor"] = True
    impostors.add_object(imp)

    # Helpers collection with non-export reference mesh
    helpers = create_col("Simple_Aircraft_Helpers")
    root.add_child(helpers)
    ref_mesh = MockObject("Reference_Blueprint_Cylinder", "MESH")
    helpers.add_object(ref_mesh)

    # Interior hierarchy
    interior_root = create_col("Simple_Aircraft_Interior")
    interior_lod0 = create_col("Simple_Aircraft_Interior_LOD0")
    interior_cams = create_col("Simple_Aircraft_Interior_Cameras")
    interior_root.add_child(interior_lod0)
    interior_lod0.add_child(interior_cams)

    cockpit_mesh = MockObject("Cockpit_LOD0", "MESH")
    interior_lod0.add_object(cockpit_mesh)
    pilot_cam = MockObject("Pilot_View", "CAMERA")
    interior_cams.add_object(pilot_cam)

    # Variant hierarchy
    variant_root = create_col("Simple_Aircraft_Floats")
    variant_lod0 = create_col("Simple_Aircraft_Floats_LOD0")
    variant_root.add_child(variant_lod0)

    float_mesh = MockObject("Pontoons_LOD0", "MESH")
    variant_lod0.add_object(float_mesh)

    all_objs = [
        f_lod0,
        w_lod0,
        datum,
        nav_light,
        cam,
        f_lod1,
        coll,
        imp,
        cockpit_mesh,
        pilot_cam,
        float_mesh,
    ]
    mock_data_objs = MockDataObjects(all_objs)

    mock_scene = type(
        "MockScene",
        (),
        {
            "collection": root,
            "lod_tool": type(
                "MockProps",
                (),
                {
                    "lods": [
                        type(
                            "MockTier",
                            (),
                            {"screen_size_pct": 100.0, "reduction_ratio": 1.0, "generated_obj": None},
                        )(),
                        type(
                            "MockTier",
                            (),
                            {"screen_size_pct": 50.0, "reduction_ratio": 0.5, "generated_obj": None},
                        )(),
                    ],
                    "target_engine": "MSFS_2024",
                    "export_directory": "//Export/",
                    "export_base_name": "Simple_Aircraft",
                    "msfs_export_full_package": True,
                    "cull_screen_size_pct": 0.5,
                },
            )(),
        },
    )()

    mock_context = type(
        "MockContext",
        (),
        {
            "scene": mock_scene,
            "view_layer": type(
                "VL",
                (),
                {
                    "objects": type("OB", (), {"active": None})(),
                    "active_layer_collection": type("ALC", (), {"collection": root})(),
                },
            )(),
        },
    )()

    mock_bpy = MagicMock()
    mock_bpy.data.collections.get = lambda name: cols.get(name)
    mock_bpy.data.collections.__iter__ = lambda s: iter(cols.values())
    mock_bpy.data.objects = mock_data_objs
    mock_bpy.context = mock_context
    mock_bpy.ops = MagicMock()
    mock_bpy.path.abspath = lambda p: p.replace("//", "")

    return mock_context, mock_bpy, cols


def test_asset_mesh_resolver_filters_technical_collections(mock_hierarchy, monkeypatch):
    """Verifies that AssetMeshResolver strictly excludes _Spatial, _Lights, and _Cameras objects."""
    import exporters.engine_export as ee

    ctx, bpy_mock, _ = mock_hierarchy
    monkeypatch.setattr(ee, "bpy", bpy_mock)

    payload = AssetMeshResolver.resolve_payload(ctx, "Simple_Aircraft")

    assert payload.asset_name == "Simple_Aircraft"
    assert payload.role == "MODEL_ROOT"
    assert 0 in payload.lod_tiers
    assert 1 in payload.lod_tiers

    # LOD0 mesh verification
    lod0_mesh_names = [o.name for o in payload.lod_tiers[0]]
    assert "Fuselage_LOD0" in lod0_mesh_names
    assert "Wing_LOD0" in lod0_mesh_names

    # Ensure technical subcollection objects are 100% excluded
    all_tier_names = [o.name for objs in payload.lod_tiers.values() for o in objs]
    assert "MSFS_Datum" not in all_tier_names
    assert "Light_Nav_Left" not in all_tier_names
    assert "Eyepoint" not in all_tier_names
    assert "Reference_Blueprint_Cylinder" not in all_tier_names

    # Collider and Impostor routing
    assert len(payload.collider_objects) == 1
    assert payload.collider_objects[0].name == "Fuselage_Collider"
    assert payload.impostor_object is not None
    assert payload.impostor_object.name == "Fuselage_Impostor"


def test_asset_mesh_resolver_identifies_interior_and_variant(mock_hierarchy, monkeypatch):
    """Verifies role classification and parent asset resolution for Interior and Variants."""
    import exporters.engine_export as ee

    ctx, bpy_mock, _ = mock_hierarchy
    monkeypatch.setattr(ee, "bpy", bpy_mock)

    interior_payload = AssetMeshResolver.resolve_payload(ctx, "Simple_Aircraft_Interior")
    assert interior_payload.role == "INTERIOR"
    assert interior_payload.parent_asset_name == "Simple_Aircraft"
    assert len(interior_payload.lod_tiers[0]) == 1
    assert interior_payload.lod_tiers[0][0].name == "Cockpit_LOD0"

    variant_payload = AssetMeshResolver.resolve_payload(ctx, "Simple_Aircraft_Floats")
    assert variant_payload.role == "VARIANT"
    assert variant_payload.parent_asset_name == "Simple_Aircraft"
    assert len(variant_payload.lod_tiers[0]) == 1
    assert variant_payload.lod_tiers[0][0].name == "Pontoons_LOD0"


def test_msfs_package_export_structure(mock_hierarchy, tmp_path, monkeypatch):
    """Verifies MSFS full package export writes model/ and model.<var>/ folders and valid model.cfg files."""
    import exporters.engine_export as ee
    import exporters.msfs_export as me

    ctx, bpy_mock, _ = mock_hierarchy
    monkeypatch.setattr(ee, "bpy", bpy_mock)
    monkeypatch.setattr(me, "bpy", bpy_mock)

    export_root = str(tmp_path / "ExportAircraft")
    ok, msg = MSFSExporter.export_project_package(ctx, export_root, "Simple_Aircraft")

    assert ok is True
    assert "MSFS package" in msg

    # Verify model/ folder and model.cfg
    model_cfg_path = os.path.join(export_root, "model", "model.cfg")
    assert os.path.exists(model_cfg_path)
    with open(model_cfg_path, "r", encoding="utf-8") as f:
        model_cfg_content = f.read()
    assert "normal=Simple_Aircraft.xml" in model_cfg_content
    assert "interior=Simple_Aircraft_Interior.xml" in model_cfg_content

    # Verify model.floats/ folder and model.cfg
    variant_cfg_path = os.path.join(export_root, "model.floats", "model.cfg")
    assert os.path.exists(variant_cfg_path)
    with open(variant_cfg_path, "r", encoding="utf-8") as vf:
        variant_cfg_content = vf.read()
    assert "normal=Simple_Aircraft_Floats.xml" in variant_cfg_content
    assert "interior=../model/Simple_Aircraft_Interior.xml" in variant_cfg_content
    # Forward slashes check
    assert "\\" not in variant_cfg_content


def test_ue5_export_transactional_rollback(mock_hierarchy, tmp_path, monkeypatch):
    """Verifies that UE5Exporter restores object names and parenting after export."""
    import exporters.engine_export as ee
    import exporters.ue5_export as ue

    ctx, bpy_mock, _ = mock_hierarchy
    monkeypatch.setattr(ee, "bpy", bpy_mock)
    monkeypatch.setattr(ue, "bpy", bpy_mock)

    # Set up original parents
    orig_parent = MockObject("OriginalRoot", "EMPTY")
    for obj in bpy_mock.data.objects:
        obj.parent = orig_parent

    coll_obj = next(o for o in bpy_mock.data.objects if o.name == "Fuselage_Collider")
    original_coll_name = coll_obj.name

    export_path = str(tmp_path / "UE5_Export")
    ok, _ = UE5Exporter.export_asset(ctx, export_path, "Simple_Aircraft")

    assert ok is True
    # Ensure collider name was restored
    assert coll_obj.name == original_coll_name
    # Ensure parents were restored
    for obj in bpy_mock.data.objects:
        assert obj.parent == orig_parent


def test_godot_export_transactional_rollback(mock_hierarchy, tmp_path, monkeypatch):
    """Verifies that GodotExporter restores custom properties and collider names after export."""
    import exporters.engine_export as ee
    import exporters.godot_export as ge

    ctx, bpy_mock, _ = mock_hierarchy
    monkeypatch.setattr(ee, "bpy", bpy_mock)
    monkeypatch.setattr(ge, "bpy", bpy_mock)

    mesh_obj = next(o for o in bpy_mock.data.objects if o.name == "Fuselage_LOD0")
    mesh_obj["custom_tag"] = "pre_existing"

    coll_obj = next(o for o in bpy_mock.data.objects if o.name == "Fuselage_Collider")
    original_coll_name = coll_obj.name

    export_path = str(tmp_path / "Godot_Export")
    ok, _ = GodotExporter.export_asset(ctx, export_path, "Simple_Aircraft")

    assert ok is True
    # Ensure collider name restored
    assert coll_obj.name == original_coll_name
    # Ensure visibility properties cleaned up and existing custom property preserved
    assert "visibility_range_begin" not in mesh_obj
    assert mesh_obj.get("custom_tag") == "pre_existing"


def test_unity_export_asset_gathering(mock_hierarchy, tmp_path, monkeypatch):
    """Verifies that UnityExporter exports pure geometry without technical markers."""
    import exporters.engine_export as ee
    import exporters.unity_export as un

    ctx, bpy_mock, _ = mock_hierarchy
    monkeypatch.setattr(ee, "bpy", bpy_mock)
    monkeypatch.setattr(un, "bpy", bpy_mock)

    export_path = str(tmp_path / "Unity_Export")
    ok, msg = UnityExporter.export_asset(ctx, export_path, "Simple_Aircraft")

    assert ok is True
    assert "Unity FBX package" in msg
    assert "exported to" in msg


def test_preflight_validator_auto_asset_resolution(mock_hierarchy, monkeypatch):
    """Verifies that PreFlightValidator resolves active_asset == 'AUTO' without defaulting to dummy 'SM_Asset'."""
    import exporters.engine_export as ee
    from exporters.engine_export import PreFlightValidator

    ctx, bpy_mock, _ = mock_hierarchy
    monkeypatch.setattr(ee, "bpy", bpy_mock)

    # Empty export_base_name and AUTO active_asset
    ctx.scene.lod_tool.export_base_name = ""
    ctx.scene.lod_tool.active_asset = "AUTO"

    # Active layer collection points to Simple_Aircraft
    coll_sa = next(c for c in bpy_mock.data.collections if c.name == "Simple_Aircraft")
    ctx.view_layer.active_layer_collection.collection = coll_sa

    errors = PreFlightValidator.run_checks(ctx)
    assert errors == [], f"Expected 0 errors with AUTO asset resolution, got: {errors}"


def test_unity_export_collider_normalization_and_rollback(mock_hierarchy, tmp_path, monkeypatch):
    """Verifies that UnityExporter normalizes non-conforming collider names and rolls them back."""
    import exporters.engine_export as ee
    import exporters.unity_export as un

    ctx, bpy_mock, _ = mock_hierarchy
    monkeypatch.setattr(ee, "bpy", bpy_mock)
    monkeypatch.setattr(un, "bpy", bpy_mock)

    coll_obj = next(o for o in bpy_mock.data.objects if o.name == "Fuselage_Collider")
    orig_name = coll_obj.name

    export_path = str(tmp_path / "Unity_Export_Norm")
    ok, _ = UnityExporter.export_asset(ctx, export_path, "Simple_Aircraft")

    assert ok is True
    assert coll_obj.name == orig_name


def test_o1_triangle_counting():
    """Verifies O(1) loop-poly invariant and degenerate 2-gon protection."""
    from core.lod_generator import _count_triangles
    from unittest.mock import MagicMock

    # Quad: 4 loops, 1 polygon -> 4 - 2 = 2 triangles
    mock_mesh = MagicMock()
    mock_mesh.loops = [object(), object(), object(), object()]
    mock_mesh.polygons = [object()]
    assert _count_triangles(mock_mesh) == 2

    # Triangle: 3 loops, 1 polygon -> 3 - 2 = 1 triangle
    mock_mesh.loops = [object(), object(), object()]
    mock_mesh.polygons = [object()]
    assert _count_triangles(mock_mesh) == 1

    # Empty
    mock_mesh.loops = []
    mock_mesh.polygons = []
    assert _count_triangles(mock_mesh) == 0

    # Fallback to polygon vertex count if loops missing
    mock_fallback = MagicMock()
    mock_fallback.loops = None
    poly1 = MagicMock()
    poly1.vertices = [0, 1]  # Degenerate 2-gon
    poly2 = MagicMock()
    poly2.vertices = [0, 1, 2, 3]  # Quad
    mock_fallback.polygons = [poly1, poly2]
    assert _count_triangles(mock_fallback) == 2


def test_aabb_centered_bounding_sphere():
    """Verifies that dense vertex clusters do not skew the sphere center or inflate radius."""
    from core.metrics import compute_bounding_sphere

    # Asymmetric model: 100 vertices at x=0 and 1 vertex at x=50
    coords = [(0.0, 0.0, 0.0)] * 100 + [(50.0, 0.0, 0.0)]

    center, radius = compute_bounding_sphere(coords)
    assert abs(center[0] - 25.0) < 1e-4
    assert abs(center[1] - 0.0) < 1e-4
    assert abs(center[2] - 0.0) < 1e-4
    assert abs(radius - 25.0) < 1e-4


def test_msfs_xml_minsize_descending_monotonicity():
    """Verifies that terminal cull size never violates descending monotonicity in XML."""
    from exporters.msfs_export import MSFSExporter

    tiers = [
        {"screen_size_pct": 100.0},
        {"screen_size_pct": 20.0},
        {"screen_size_pct": 2.0},
    ]
    xml_str = MSFSExporter.generate_model_info_xml("Aircraft", tiers, cull_screen_size_pct=5.0)
    assert "<LODS>" in xml_str
    assert 'minSize="20"' in xml_str
    assert 'minSize="2"' in xml_str
    # Terminal cull size clamped strictly less than 2.0 -> 1.9
    assert 'minSize="1.9"' in xml_str


def test_parse_model_xml_bom_and_encoding(tmp_path):
    """Verifies parse_model_xml handles UTF-8 with BOM gracefully."""
    from core.msfs_project_scanner import parse_model_xml

    xml_file = tmp_path / "ModelWithBOM.xml"
    content = '<?xml version="1.0" encoding="utf-8"?>\n<ModelInfo>\n  <LODS>\n    <LOD minSize="25" ModelFile="Model_LOD0.gltf"/>\n  </LODS>\n</ModelInfo>'
    xml_file.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))

    lods = parse_model_xml(xml_file)
    assert len(lods) == 1
    assert lods[0].min_size == 25.0
    assert lods[0].gltf_path.name == "Model_LOD0.gltf"


def test_unified_export_asset_resolution():
    """Verifies resolve_export_asset_name prioritizes active_asset when set."""
    from exporters.engine_export import resolve_export_asset_name
    from unittest.mock import MagicMock

    mock_props = MagicMock()
    mock_props.active_asset = "Wasm_Aircraft_Interior"
    mock_props.export_base_name = "Wasm_Aircraft"

    resolved = resolve_export_asset_name(None, mock_props)
    assert resolved == "Wasm_Aircraft_Interior"

    mock_props.active_asset = "AUTO"
    resolved_auto = resolve_export_asset_name(None, mock_props)
    assert resolved_auto == "Wasm_Aircraft"
