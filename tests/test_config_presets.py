"""
Automated Pytest Suite for Config Presets, Extended MSFS Config Objects,
and Non-Destructive Geometry-Anchored Marker Spawning.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.config_presets import (
    DEFAULT_CONFIG_PRESET_ID,
    ConfigPresetManager,
    delete_config_preset,
    get_config_preset,
    list_config_presets,
    save_config_preset,
)
from core.msfs.cst_parser import MSFSCSTParser
from core.msfs.models import AerodynamicPoint, EnginePoint, ExitPoint


# =============================================================================
# PRESET MANAGER TESTS
# =============================================================================


def test_builtin_config_presets_exist():
    """Verify built-in factory presets exist and have valid structure."""
    presets = list_config_presets()
    preset_ids = [p["preset_id"] for p in presets]

    assert DEFAULT_CONFIG_PRESET_ID in preset_ids
    assert "plane_general_aviation" in preset_ids
    assert "plane_commercial_airliner" in preset_ids
    assert "plane_taildragger" in preset_ids
    assert "plane_playermodel" in preset_ids
    assert "plane_ai_npc" in preset_ids
    assert "car_playermodel" in preset_ids
    assert "car_npc" in preset_ids

    # Plane - Playermodel archetype
    plane_player = get_config_preset("plane_playermodel")
    assert plane_player is not None
    assert plane_player["name"] == "Plane - Playermodel"
    assert len(plane_player["interactions"]) > 0

    # Car - Playermodel archetype
    car_player = get_config_preset("car_playermodel")
    assert car_player is not None
    assert car_player["name"] == "Car - Playermodel"
    assert len(car_player["spatial"]) >= 4

    ga = get_config_preset("plane_general_aviation")
    assert ga is not None
    assert ga["name"] == "General Aviation (Single/Twin)"
    assert "spatial" in ga
    assert "lights" in ga
    assert "cameras" in ga
    assert "exits" in ga
    assert "engines" in ga

    airliner = get_config_preset("plane_commercial_airliner")
    assert airliner is not None
    assert airliner["name"] == "Commercial Airliner (Twin-Jet)"
    assert len(airliner["engines"]) == 2
    assert len(airliner["exits"]) >= 2

    taildragger = get_config_preset("plane_taildragger")
    assert taildragger is not None
    assert taildragger["name"] == "Taildragger (Tailwheel GA)"
    # Taildragger should have main wheels forward and tailwheel aft
    cp_ids = [p["id"] for p in taildragger["spatial"]]
    assert "CONTACT_POINTS:point.0" in cp_ids


def test_config_preset_schema_validation():
    """Verify schema validator enforces types, defaults, and rejection rules."""
    # Must have name
    assert ConfigPresetManager.validate_preset_schema({}) is None

    minimal = {"name": "Minimal Preset"}
    validated = ConfigPresetManager.validate_preset_schema(minimal)
    assert validated is not None
    assert validated["name"] == "Minimal Preset"
    assert validated["archetype"] == "general_aviation"
    assert isinstance(validated["spatial"], list)
    assert isinstance(validated["lights"], list)
    assert isinstance(validated["cameras"], list)
    assert isinstance(validated["exits"], list)
    assert isinstance(validated["engines"], list)


def test_config_preset_user_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify saving, loading, duplicating, and deleting custom presets."""
    monkeypatch.setattr(ConfigPresetManager, "get_user_dir", classmethod(lambda cls: tmp_path))

    custom = {
        "name": "User Custom Jet",
        "category": "PLANE",
        "spatial": {
            "datum": {"anchor": "AABB_CENTER"},
            "contact_points": [
                {"id": "CONTACT_POINTS:point.0", "name": "NoseGear", "anchor": "EXTREMA_NOSE", "class": 1}
            ],
        },
        "exits": [{"id": "EXITS:exit.0", "name": "MainDoor", "anchor": "EXTREMA_WINGTIP_L", "exit_type": 0}],
        "engines": [
            {"id": "GENERALENGINEDATA:Engine.0", "name": "Turbine", "anchor": "AABB_CENTER", "engine_index": 1}
        ],
        "lights": [],
        "cameras": [],
    }

    preset_id = save_config_preset(custom)
    assert preset_id == "user_custom_jet"

    loaded = ConfigPresetManager.get_preset(preset_id)
    assert loaded["name"] == "User Custom Jet"
    assert not ConfigPresetManager.is_builtin(preset_id)

    # Duplication
    dup_id = ConfigPresetManager.duplicate_preset(preset_id, "User Custom Jet Copy")
    assert dup_id == "user_custom_jet_copy"
    dup_loaded = ConfigPresetManager.get_preset(dup_id)
    assert dup_loaded["name"] == "User Custom Jet Copy"

    # Cannot delete built-in
    assert delete_config_preset("plane_general_aviation") is False

    # Can delete custom
    assert delete_config_preset(dup_id) is True
    assert delete_config_preset(preset_id) is True


# =============================================================================
# SPATIAL PARSER TESTS (EXITS, ENGINES, AERODYNAMICS)
# =============================================================================


SYNTHETIC_AIRCRAFT_CFG = """[VERSION]
major = 1
minor = 0

[WEIGHT_AND_BALANCE]
reference_datum_position = 0, 0, 0
empty_weight_CG_position = -2.0, 0, 0.5

[CONTACT_POINTS]
point.0 = 1, 6.0, 0.0, -3.5, 1200, 0, 0.5, 25
point.1 = 1, -3.0, -5.0, -3.5, 1500, 1, 0.5, 0
point.2 = 1, -3.0, 5.0, -3.5, 1500, 2, 0.5, 0

[EXITS]
number_of_exits = 2
exit.0 = 0.4, 2.0, -3.0, 0.5, 0 ; Passenger Door
exit.1 = 0.2, -4.0, 3.0, 0.2, 1 ; Cargo Door

[GENERALENGINEDATA]
engine_type = 0
Engine.0 = 3.0, -4.5, -0.5 ; Left Engine
Engine.1 = 3.0, 4.5, -0.5 ; Right Engine

[AERODYNAMICS]
wing_apex_pos = 1.5, 0.0, 0.8
aero_center_lift = 0.5, 0.0, 0.2
"""


def test_cst_parser_with_exits_engines_aerodynamics():
    """Verify MSFSCSTParser extracts exits, engines, and aerodynamics into config."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".cfg", encoding="utf-8") as tf:
        tf.write(SYNTHETIC_AIRCRAFT_CFG)
        tf_path = tf.name

    try:
        cfg = MSFSCSTParser.parse_file(tf_path)
        assert cfg is not None
        assert len(cfg.exits) == 2
        assert len(cfg.engines) == 2

        # Verify exits
        e0 = cfg.get_point_by_id("EXITS:exit.0")
        assert isinstance(e0, ExitPoint)
        assert e0.exit_type == 0
        assert e0.open_rate == pytest.approx(0.4)

        # Verify engines
        eng0 = cfg.get_point_by_id("GENERALENGINEDATA:Engine.0")
        assert isinstance(eng0, EnginePoint)
        assert eng0.engine_index == 0

        # Verify aerodynamics
        aero_apex = cfg.get_point_by_id("AERODYNAMICS:wing_apex_pos")
        assert isinstance(aero_apex, AerodynamicPoint)
        assert aero_apex.coords_blender_m[1] == pytest.approx(1.5 * 0.3048)

        # Verify serialization roundtrip preserves sections
        backup = MSFSCSTParser.serialize_and_save(cfg, {}, target_path=tf_path)
        with open(tf_path, "r", encoding="utf-8") as f:
            out_text = f.read()
        assert "[EXITS]" in out_text
        assert "exit.0 = 0.4, 2.0, -3.0, 0.5, 0" in out_text
        assert "[GENERALENGINEDATA]" in out_text
        assert "Engine.0 = 3.0, -4.5, -0.5" in out_text
        assert "[AERODYNAMICS]" in out_text
        assert "wing_apex_pos = 1.5, 0.0, 0.8" in out_text
        if backup and Path(backup).exists():
            Path(backup).unlink(missing_ok=True)
    finally:
        Path(tf_path).unlink(missing_ok=True)


# =============================================================================
# NON-DESTRUCTIVE SPAWNING OPERATOR TESTS
# =============================================================================


def test_add_config_preset_non_destructive(monkeypatch: pytest.MonkeyPatch):
    """
    Verify OMNIMESH_OT_add_config_preset only adds missing markers
    and strictly never duplicates or overwrites existing markers.
    """
    from ui.config_preset_ops import OMNIMESH_OT_add_config_preset

    # Mock Blender context and scene hierarchy
    mock_context = MagicMock()
    mock_scene = MagicMock()
    mock_props = MagicMock()
    mock_cfg_props = MagicMock()

    mock_context.scene = mock_scene
    mock_scene.lod_tool = mock_props
    mock_props.config_presets = mock_cfg_props
    mock_cfg_props.config_preset = "plane_general_aviation"
    mock_cfg_props.include_spatial = True
    mock_cfg_props.include_exits = True
    mock_cfg_props.include_engines = True
    mock_cfg_props.include_lights = True
    mock_cfg_props.include_cameras = True

    # Setup mock collections and tracking
    spatial_objects: list[Any] = []
    lights_objects: list[Any] = []
    cameras_objects: list[Any] = []

    class MockObject:
        def __init__(self, name: str, data: Any = None):
            self.name = name
            self.data = data
            self.location = [0.0, 0.0, 0.0]
            self.rotation_euler = [0.0, 0.0, 0.0]
            self._props: dict[str, Any] = {}

        def __setitem__(self, key: str, value: Any):
            self._props[key] = value

        def __getitem__(self, key: str) -> Any:
            return self._props[key]

        def get(self, key: str, default: Any = None) -> Any:
            return self._props.get(key, default)

    class MockCollection:
        def __init__(self, name: str, obj_list: list[Any]):
            self.name = name
            self.objects = MagicMock()
            self._obj_list = obj_list
            self.objects.__iter__.side_effect = lambda: iter(self._obj_list)
            self.objects.link = lambda obj: self._obj_list.append(obj)

    spatial_col = MockCollection("TestPlane_Spatial", spatial_objects)
    lights_col = MockCollection("TestPlane_Lights", lights_objects)
    cameras_col = MockCollection("TestPlane_Cameras", cameras_objects)

    mock_hierarchy = {
        "spatial": spatial_col,
        "lights": lights_col,
        "cameras": cameras_col,
    }

    monkeypatch.setattr(
        "ui.config_preset_ops.resolve_effective_asset_name",
        lambda ctx, props: "TestPlane",
    )
    monkeypatch.setattr(
        "ui.config_preset_ops.get_asset_base_meshes",
        lambda ctx, asset: [],
    )
    monkeypatch.setattr(
        "ui.config_preset_ops.get_or_create_engine_import_collection",
        lambda ctx, asset, role: mock_hierarchy.get(role.lower(), spatial_col),
    )

    mock_bpy = MagicMock()
    mock_bpy.data.objects.new.side_effect = lambda name, data: MockObject(name, data)
    mock_bpy.data.lights.new.return_value = MagicMock()
    mock_bpy.data.cameras.new.return_value = MagicMock()

    def _mock_remove(obj, do_unlink=True):
        for col_list in (spatial_objects, lights_objects, cameras_objects):
            if obj in col_list:
                col_list.remove(obj)

    mock_bpy.data.objects.remove.side_effect = _mock_remove

    monkeypatch.setattr("ui.config_preset_ops.bpy", mock_bpy)
    monkeypatch.setattr("ui.config_preset_ops.Euler", None)

    op = OMNIMESH_OT_add_config_preset()

    # FIRST RUN: Spawns all missing markers from general aviation preset
    res1 = op.execute(mock_context)
    assert res1 == {"FINISHED"}
    initial_count = len(spatial_objects) + len(lights_objects) + len(cameras_objects)
    assert initial_count > 0

    # Verify key markers exist
    all_objs = spatial_objects + lights_objects + cameras_objects
    msfs_ids = [o.get("msfs_id") for o in all_objs if o.get("msfs_id")]
    assert "WEIGHT_AND_BALANCE:reference_datum_position" in msfs_ids
    assert "WEIGHT_AND_BALANCE:empty_weight_CG_position" in msfs_ids
    assert "CONTACT_POINTS:point.0" in msfs_ids
    assert "CAMERAS:eyepoint" in msfs_ids
    assert "EXITS:exit.0" in msfs_ids
    assert "GENERALENGINEDATA:engine.0" in msfs_ids

    # SECOND RUN: Smart Replace cleanly replaces enabled categories without duplicating
    res2 = op.execute(mock_context)
    assert res2 == {"FINISHED"}
    assert len(spatial_objects) + len(lights_objects) + len(cameras_objects) == initial_count

    # Verify ID counts are strictly 1 (no duplicates)
    all_objs_run2 = spatial_objects + lights_objects + cameras_objects
    ids_run2 = [o.get("msfs_id") for o in all_objs_run2 if o.get("msfs_id")]
    assert len(ids_run2) == len(set(ids_run2))


def test_smart_replace_and_autofit_geometry(monkeypatch: pytest.MonkeyPatch):
    """
    Verify that config preset spawner detects wheel submeshes,
    snaps wheel contact points to actual tire bottoms, aligns scrape points,
    and replaces existing objects cleanly without duplicates.
    """
    import numpy as np
    from core.msfs.preset_spawner import ConfigPresetSpawner

    mock_context = MagicMock()
    mock_bpy = MagicMock()

    class MockMeshObject:
        def __init__(self, name: str, bbox: list[tuple[float, float, float]]):
            self.name = name
            self.type = "MESH"
            self.data = MagicMock()
            self.data.vertices = [MagicMock() for _ in bbox]
            self.matrix_world = MagicMock()
            self._bbox = bbox

        @property
        def bound_box(self):
            return self._bbox

    # Simulate aircraft with separate wheel submeshes and fuselage
    # Nose wheel center: (0.0, 4.0), bottom: -1.2
    nose_wheel = MockMeshObject("Wheel_Nose", [(-0.2, 3.8, -1.2), (0.2, 4.2, -0.6)])
    # Left wheel center: (-2.5, -0.5), bottom: -1.3
    left_wheel = MockMeshObject("Main_Gear_Left_Tire", [(-2.7, -0.7, -1.3), (-2.3, -0.3, -0.7)])
    # Right wheel center: (2.5, -0.5), bottom: -1.3
    right_wheel = MockMeshObject("Main_Gear_Right_Tire", [(2.3, -0.7, -1.3), (2.7, -0.3, -0.7)])
    # Fuselage
    fuselage = MockMeshObject("Fuselage", [(-3.0, -6.0, -0.5), (3.0, 5.0, 2.5)])

    base_meshes = [nose_wheel, left_wheel, right_wheel, fuselage]

    # Mock extract_world_vertices_numpy
    def _mock_extract(obj):
        if hasattr(obj, "_bbox"):
            pts = []
            for b in obj._bbox:
                pts.append(b)
            return np.array(pts, dtype=np.float32)
        return np.empty((0, 3), dtype=np.float32)

    monkeypatch.setattr("core.msfs.geometry.extract_world_vertices_numpy", _mock_extract)

    # Collections
    spatial_objs: list[Any] = []
    lights_objs: list[Any] = []
    cameras_objs: list[Any] = []

    class MockCol:
        def __init__(self, name: str, o_list: list[Any]):
            self.name = name
            self._list = o_list
            self.objects = MagicMock()
            self.objects.__iter__.side_effect = lambda: iter(self._list)
            self.objects.link = lambda obj: self._list.append(obj)

    def _col_fn(_ctx, _asset, role):
        r = role.upper()
        if r == "SPATIAL":
            return MockCol("Plane_Spatial", spatial_objs)
        elif r == "LIGHTS":
            return MockCol("Plane_Lights", lights_objs)
        elif r == "CAMERAS":
            return MockCol("Plane_Cameras", cameras_objs)
        return MockCol("Plane_Other", [])

    class MockSpawnObject:
        def __init__(self, name: str, data: Any = None):
            self.name = name
            self.data = data
            self.location = (0.0, 0.0, 0.0)
            self._dict: dict[str, Any] = {}

        def __setitem__(self, k, v):
            self._dict[k] = v

        def __getitem__(self, k):
            return self._dict[k]

        def get(self, k, d=None):
            return self._dict.get(k, d)

    mock_bpy.data.objects.new.side_effect = lambda name, data: MockSpawnObject(name, data)
    mock_bpy.data.lights.new.return_value = MagicMock()
    mock_bpy.data.cameras.new.return_value = MagicMock()

    def _remove_side_effect(obj, do_unlink=True):
        for lst in (spatial_objs, lights_objs, cameras_objs):
            if obj in lst:
                lst.remove(obj)

    mock_bpy.data.objects.remove.side_effect = _remove_side_effect

    preset = get_config_preset("plane_general_aviation")

    # Spawning pass 1
    added1 = ConfigPresetSpawner.spawn_preset_objects(
        context=mock_context,
        asset_name="TestPlane",
        preset_data=preset,
        bpy_module=mock_bpy,
        get_base_meshes_fn=lambda _ctx, _a: base_meshes,
        get_import_collection_fn=_col_fn,
    )
    assert added1 > 0
    total1 = len(spatial_objs) + len(lights_objs) + len(cameras_objs)

    # Verify wheel contact points snapped to detected tire bottoms
    pt0 = next((o for o in spatial_objs if o.get("msfs_key") == "point.0"), None)
    assert pt0 is not None
    # Nose wheel bottom is -1.2
    assert pt0.location[1] == pytest.approx(4.0, abs=0.1)
    assert pt0.location[2] == pytest.approx(-1.2, abs=0.1)

    pt1 = next((o for o in spatial_objs if o.get("msfs_key") == "point.1"), None)
    assert pt1 is not None
    # Left wheel bottom is -1.3, X is -2.5
    assert pt1.location[0] == pytest.approx(-2.5, abs=0.1)
    assert pt1.location[2] == pytest.approx(-1.3, abs=0.1)

    # Spawning pass 2: Smart replace must replace without duplicates
    added2 = ConfigPresetSpawner.spawn_preset_objects(
        context=mock_context,
        asset_name="TestPlane",
        preset_data=preset,
        bpy_module=mock_bpy,
        get_base_meshes_fn=lambda _ctx, _a: base_meshes,
        get_import_collection_fn=_col_fn,
    )
    total2 = len(spatial_objs) + len(lights_objs) + len(cameras_objs)
    assert total2 == total1
    assert added2 > 0
