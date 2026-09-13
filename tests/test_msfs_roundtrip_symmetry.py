"""
Automated Pytest Suite for MSFS Roundtrip Symmetry & Disambiguation:
1. Quote-aware station_load.N parsing & lossless serialization without Datum/CG corruption (H-02).
2. [EXITS] roundtrip preserving open_rate and exit_type.
3. classify_imported_mesh_node disambiguation: Exterior crash colliders vs Exterior/Interior clickspots (H-01).
4. Extended Factory Presets (plane_seaplane, helicopter_standard, glider_sailplane) schema validation.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.config_presets import (
    ConfigPresetManager,
    get_config_preset,
    list_config_presets,
)
from core.gltf_assembly import classify_imported_mesh_node
from core.msfs.cst_parser import MSFSCSTParser


# =============================================================================
# 1. STATION_LOAD.N QUOTE-AWARE PARSING & SERIALIZATION ROUNDTRIP (H-02)
# =============================================================================


def test_station_load_quote_aware_parsing_and_serialization():
    """Verify station_load.N lines with quoted strings and embedded commas parse and serialize accurately."""
    cfg_content = """[WEIGHT_AND_BALANCE]
reference_datum_position = 0, 0, 0
empty_weight_cg_position = -1.5, 0, 0
station_load.0 = 170, 2.5, -1.2, 0.5, "Pilot, Captain", 1
station_load.1 = 170, 2.5, 1.2, 0.5, "Co-Pilot, First Officer", 1
station_load.2 = 80, -4.0, 0.0, -0.2, "Baggage, Aft", 6
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as f:
        f.write(cfg_content)
        temp_path = f.name

    out_path = ""
    try:
        config = MSFSCSTParser.parse_file(temp_path)

        assert len(config.station_loads) == 3

        load0 = config.station_loads[0]
        assert load0.point_id == "WEIGHT_AND_BALANCE:station_load.0"
        assert load0.weight_lbs == 170.0
        assert load0.coords_msfs_rel_ft == (2.5, -1.2, 0.5)
        assert load0.station_name == "Pilot, Captain"
        assert load0.station_type == 1

        load2 = config.station_loads[2]
        assert load2.weight_lbs == 80.0
        assert load2.coords_msfs_rel_ft == (-4.0, 0.0, -0.2)
        assert load2.station_name == "Baggage, Aft"
        assert load2.station_type == 6

        # Update coordinates of station_load.1 and empty_weight_cg_position
        updated_points = {
            "WEIGHT_AND_BALANCE:station_load.1": (2.8, 1.3, 0.6),
            "WEIGHT_AND_BALANCE:empty_weight_cg_position": (-1.6, 0.0, 0.1),
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as out_f:
            out_path = out_f.name

        MSFSCSTParser.serialize_and_save(config, updated_points, target_path=out_path)

        # Read back and verify
        reloaded = MSFSCSTParser.parse_file(out_path)
        assert reloaded.empty_weight_cg_ft == (-1.6, 0.0, 0.1)

        reloaded_load1 = reloaded.station_loads[1]
        assert reloaded_load1.coords_msfs_rel_ft == (2.8, 1.3, 0.6)
        assert reloaded_load1.station_name == "Co-Pilot, First Officer"
        assert reloaded_load1.weight_lbs == 170.0

        # Verify load0 was untouched
        assert reloaded.station_loads[0].coords_msfs_rel_ft == (2.5, -1.2, 0.5)
        assert reloaded.station_loads[0].station_name == "Pilot, Captain"

        # Verify raw text structure in output file
        content = Path(out_path).read_text(encoding="utf-8")
        assert 'station_load.1 = 170, 2.8, 1.3, 0.6, "Co-Pilot, First Officer", 1' in content
        assert "empty_weight_cg_position = -1.6, 0, 0.1" in content
    finally:
        Path(temp_path).unlink(missing_ok=True)
        Path(out_path).unlink(missing_ok=True)


# =============================================================================
# 2. [EXITS] SERIALIZATION ROUNDTRIP (OPEN_RATE & EXIT_TYPE)
# =============================================================================


def test_exits_parsing_and_serialization_roundtrip():
    """Verify [EXITS] lines preserve open_rate, exit_type, and coordinates."""
    cfg_content = """[EXITS]
number_of_exits = 2
exit.0 = 0.4, -5.2, -4.5, 1.2, 0 ; Main door
exit.1 = 0.2, 10.5, 3.2, 0.0, 1 ; Cargo hatch
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as f:
        f.write(cfg_content)
        temp_path = f.name

    out_path = ""
    try:
        config = MSFSCSTParser.parse_file(temp_path)
        assert len(config.exits) == 2

        exit0 = config.exits[0]
        assert exit0.point_id == "EXITS:exit.0"
        assert exit0.open_rate == 0.4
        assert exit0.coords_msfs_rel_ft == (-5.2, -4.5, 1.2)
        assert exit0.exit_type == 0

        exit1 = config.exits[1]
        assert exit1.open_rate == 0.2
        assert exit1.coords_msfs_rel_ft == (10.5, 3.2, 0.0)
        assert exit1.exit_type == 1

        # Modify exit.0 coordinates
        updated_points = {
            "EXITS:exit.0": (-5.5, -4.6, 1.3),
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as out_f:
            out_path = out_f.name

        MSFSCSTParser.serialize_and_save(config, updated_points, target_path=out_path)

        reloaded = MSFSCSTParser.parse_file(out_path)
        assert len(reloaded.exits) == 2
        assert reloaded.exits[0].coords_msfs_rel_ft == (-5.5, -4.6, 1.3)
        assert reloaded.exits[0].open_rate == 0.4
        assert reloaded.exits[0].exit_type == 0

        content = Path(out_path).read_text(encoding="utf-8")
        assert "exit.0 = 0.4, -5.5, -4.6, 1.3, 0 ; Main door" in content
    finally:
        Path(temp_path).unlink(missing_ok=True)
        Path(out_path).unlink(missing_ok=True)


# =============================================================================
# 3. CLASSIFY_IMPORTED_MESH_NODE DISAMBIGUATION (H-01)
# =============================================================================


def test_classify_imported_mesh_node_disambiguation():
    """Verify disambiguation between render meshes, exterior crash colliders, and cockpit clickspots."""
    # 1. Normal render mesh
    obj_render = MagicMock()
    obj_render.type = "MESH"
    obj_render.name = "Fuselage_Main"
    obj_render.get = MagicMock(return_value=None)
    obj_render.data.materials = []
    assert classify_imported_mesh_node(obj_render, is_interior=False) == "RENDER_MESH"

    # 2. Exterior crash hull with 'Collision_' prefix and large bounding diagonal
    obj_crash_hull = MagicMock()
    obj_crash_hull.type = "MESH"
    obj_crash_hull.name = "Collision_Fuselage"
    obj_crash_hull.get = MagicMock(return_value=None)
    obj_crash_hull.dimensions.x = 2.0
    obj_crash_hull.dimensions.y = 8.0
    obj_crash_hull.dimensions.z = 2.0
    obj_crash_hull.data.materials = []
    assert classify_imported_mesh_node(obj_crash_hull, is_interior=False) == "PHYSICS_COLLIDER"

    # 3. Cockpit clickspot with button naming
    obj_button = MagicMock()
    obj_button.type = "MESH"
    obj_button.name = "Collision_Button_MasterCaution"
    obj_button.get = MagicMock(return_value=None)
    obj_button.dimensions.x = 0.05
    obj_button.dimensions.y = 0.05
    obj_button.dimensions.z = 0.02
    assert classify_imported_mesh_node(obj_button, is_interior=True) == "INTERACTION_VOLUME"

    # 4. Exterior clickspot with switch/handle naming (e.g. external fuel cap / door handle)
    obj_ext_clickspot = MagicMock()
    obj_ext_clickspot.type = "MESH"
    obj_ext_clickspot.name = "Collision_Handle_BaggageDoor"
    obj_ext_clickspot.get = MagicMock(return_value=None)
    assert classify_imported_mesh_node(obj_ext_clickspot, is_interior=False) == "INTERACTION_VOLUME"

    # 5. Interior small collision mesh without button prefix (e.g. unnamed clickspot <= 0.45m)
    obj_interior_clickspot = MagicMock()
    obj_interior_clickspot.type = "MESH"
    obj_interior_clickspot.name = "Collision_AuxPanel"
    obj_interior_clickspot.get = MagicMock(return_value=None)
    obj_interior_clickspot.dimensions.x = 0.2
    obj_interior_clickspot.dimensions.y = 0.2
    obj_interior_clickspot.dimensions.z = 0.1  # diag ~0.3m <= 0.45m
    assert classify_imported_mesh_node(obj_interior_clickspot, is_interior=True) == "INTERACTION_VOLUME"

    # 6. Interior large crash barrier (diag > 0.45m)
    obj_interior_barrier = MagicMock()
    obj_interior_barrier.type = "MESH"
    obj_interior_barrier.name = "Collision_CabinFloor"
    obj_interior_barrier.get = MagicMock(return_value=None)
    obj_interior_barrier.dimensions.x = 1.5
    obj_interior_barrier.dimensions.y = 3.0
    obj_interior_barrier.dimensions.z = 0.1  # diag > 3.0m
    assert classify_imported_mesh_node(obj_interior_barrier, is_interior=True) == "PHYSICS_COLLIDER"

    # 7. Explicit flags override
    obj_flagged = MagicMock()
    obj_flagged.type = "MESH"
    obj_flagged.name = "CustomMesh"
    obj_flagged.get = MagicMock(side_effect=lambda k: True if k == "_is_trigger" else None)
    assert classify_imported_mesh_node(obj_flagged) == "INTERACTION_VOLUME"


# =============================================================================
# 4. EXTENDED FACTORY PRESETS SCHEMA VALIDATION
# =============================================================================


def test_extended_factory_presets_schema_and_contents():
    """Verify new factory presets (plane_seaplane, helicopter_standard, glider_sailplane) load and validate cleanly."""
    # Verify all built-in presets validate
    presets = list_config_presets()
    preset_ids = [p["preset_id"] for p in presets]

    assert "plane_seaplane" in preset_ids
    assert "helicopter_standard" in preset_ids
    assert "glider_sailplane" in preset_ids

    # 1. Seaplane
    seaplane = get_config_preset("plane_seaplane")
    assert seaplane is not None
    assert seaplane["name"] == "Seaplane / Floatplane"
    ConfigPresetManager.validate_preset_schema(seaplane)

    # Class 4 water rudders / floats present
    contact_classes = [cp.get("point_class") for cp in seaplane.get("spatial", []) if "point_class" in cp]
    assert 4 in contact_classes
    assert len(seaplane.get("station_loads", [])) >= 2
    assert len(seaplane.get("interactions", [])) >= 2

    # 2. Helicopter
    heli = get_config_preset("helicopter_standard")
    assert heli is not None
    assert heli["name"] == "Helicopter (Turbine / Piston)"
    ConfigPresetManager.validate_preset_schema(heli)

    # Class 3 skids present
    heli_classes = [cp.get("point_class") for cp in heli.get("spatial", []) if "point_class" in cp]
    assert 3 in heli_classes
    # Collective and cyclic interaction volumes present
    interaction_names = [iv.get("name") for iv in heli.get("interactions", [])]
    assert "Cyclic_Stick" in interaction_names
    assert "Collective_Lever" in interaction_names

    # 3. Glider
    glider = get_config_preset("glider_sailplane")
    assert glider is not None
    assert glider["name"] == "Glider / Sailplane"
    ConfigPresetManager.validate_preset_schema(glider)

    # Airbrake lever & tow hook release present
    glider_interactions = [iv.get("name") for iv in glider.get("interactions", [])]
    assert "Tow_Release_Knob" in glider_interactions
    assert "Airbrake_Spoiler_Lever" in glider_interactions
    # Ballast tanks in fuel / ballast section
    ballast_names = [s.get("name") for s in glider.get("spatial", []) if "Ballast" in s.get("name", "")]
    assert len(ballast_names) >= 2


# =============================================================================
# 5. INTEGRATION TEST AGAINST REAL MSFS 2024 SDK SAMPLES
# =============================================================================


def test_real_msfs_sdk_samples_pipeline():
    """Verify scanner, CST parser, XML merger, and model options on real MSFS SDK sample aircraft."""
    sdk_root = Path(r"C:\MSFS 2024 SDK\Samples\DevmodeProjects\SimObjects\Aircraft")
    if not sdk_root.exists():
        pytest.skip("MSFS 2024 SDK Samples directory not found on host machine.")

    from core.msfs.project_scanner import MSFSProjectScanner
    from core.msfs_xml_merger import ModelXMLMerger

    # 1. Test SimpleAircraft
    simple_ac_dir = sdk_root / "SimpleAircraft"
    manifest_simple = MSFSProjectScanner.scan(simple_ac_dir)
    assert manifest_simple.has_geometry
    assert "normal" in manifest_simple.models
    assert len(manifest_simple.models["normal"].lods) == 5
    assert manifest_simple.model_options.is_msfs_2024 is True
    assert manifest_simple.flight_model_cfg_path is not None

    # Verify SimpleAircraft flight_model.cfg roundtrip
    cfg_simple = MSFSCSTParser.parse_file(str(manifest_simple.flight_model_cfg_path))
    assert len(cfg_simple.station_loads) == 7
    assert cfg_simple.station_loads[0].station_name == "Pilot"
    assert cfg_simple.reference_datum_ft == (3.6, 0.0, 0.0)

    # Test surgical XML merger on real SimpleAircraft.xml without breaking animations
    simple_xml = manifest_simple.models["normal"].xml_path
    assert simple_xml is not None and simple_xml.is_file()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False) as tmp_f:
        tmp_xml_path = tmp_f.name

    try:
        import shutil

        shutil.copy2(simple_xml, tmp_xml_path)
        new_lods = [
            {"min_size": 60.0, "filename": "SimpleAircraft_LOD00.gltf"},
            {"min_size": 25.0, "filename": "SimpleAircraft_LOD01.gltf"},
            {"min_size": 1.0, "filename": "SimpleAircraft_LOD02.gltf"},
        ]
        assert ModelXMLMerger.merge_lods_file(tmp_xml_path, new_lods)
        xml_content = Path(tmp_xml_path).read_text(encoding="utf-8")
        assert 'minSize="60' in xml_content
        assert "c_wheel" in xml_content  # Animation block preserved
        assert "(A:GEAR CENTER STEER ANGLE, grads)" in xml_content  # RPN code intact
    finally:
        Path(tmp_xml_path).unlink(missing_ok=True)

    # 2. Test WasmAircraft (Multi-Model: Exterior & Interior)
    wasm_ac_dir = sdk_root / "WasmAircraft"
    manifest_wasm = MSFSProjectScanner.scan(wasm_ac_dir)
    assert manifest_wasm.has_geometry
    assert "normal" in manifest_wasm.models
    assert "interior" in manifest_wasm.models
    assert len(manifest_wasm.models["normal"].lods) == 5
    assert len(manifest_wasm.models["interior"].lods) == 5
    assert manifest_wasm.model_options.with_exterior_show_interior is True
    assert manifest_wasm.model_options.with_interior_force_first_lod is True

    # 3. Test DA62 and Cabri_G2 auto-discovery
    da62_dir = sdk_root / "DA62"
    manifest_da62 = MSFSProjectScanner.scan(da62_dir)
    assert manifest_da62.model_cfg_path is not None
    assert manifest_da62.flight_model_cfg_path is not None
    assert "interior" in manifest_da62.models
    assert "normal" in manifest_da62.models
