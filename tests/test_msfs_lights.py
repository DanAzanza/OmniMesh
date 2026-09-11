"""
Automated Pytest Suite for MSFS Lighting Pipeline & Symmetry Kinematics.
Tests aerospace-to-lamp rotation math, mirroring kinematics, CST insertion into systems.cfg,
and real MSFS 2024 SDK SimpleAircraft light parsing.
"""

from __future__ import annotations

import os
import tempfile
import pytest

from core.msfs_cst_parser import MSFSCSTParser
from core.msfs_models import CFGLineRecord
from core.msfs_transforms import (
    _euler_xyz_to_matrix,
    blender_rotation_to_msfs_pbh,
    mirror_pbh_rotation,
    mirror_spatial_coords,
    msfs_pbh_to_blender_rotation,
)


def test_spotlight_forward_orientation():
    """Verify MSFS (0,0,0) PBH points Blender spotlight along longitudinal forward (+Y)."""
    rx, ry, rz = msfs_pbh_to_blender_rotation(0.0, 0.0, 0.0)

    # Blender spotlights emit along local -Z ([0, 0, -1])
    m_spot = _euler_xyz_to_matrix(rx, ry, rz)
    emit_dir = [
        m_spot[0][0] * 0 + m_spot[0][1] * 0 + m_spot[0][2] * -1,
        m_spot[1][0] * 0 + m_spot[1][1] * 0 + m_spot[1][2] * -1,
        m_spot[2][0] * 0 + m_spot[2][1] * 0 + m_spot[2][2] * -1,
    ]

    # Must point straight forward along +Y ([0, 1, 0])
    assert abs(emit_dir[0] - 0.0) < 1e-5
    assert abs(emit_dir[1] - 1.0) < 1e-5
    assert abs(emit_dir[2] - 0.0) < 1e-5

    # Inverse round-trip
    p, b, h = blender_rotation_to_msfs_pbh(rx, ry, rz)
    assert abs(p - 0.0) < 1e-4
    assert abs(b - 0.0) < 1e-4
    assert abs(h - 0.0) < 1e-4


def test_landing_light_pitched_down():
    """Verify landing light tilted down 10 deg points forward (+Y) and downward (-Z)."""
    rx, ry, rz = msfs_pbh_to_blender_rotation(10.0, 0.0, 0.0)

    m_spot = _euler_xyz_to_matrix(rx, ry, rz)
    emit_dir = [
        -m_spot[0][2],
        -m_spot[1][2],
        -m_spot[2][2],
    ]

    assert abs(emit_dir[0]) < 1e-5
    assert emit_dir[1] > 0.95  # forward
    assert emit_dir[2] < -0.15  # downward pitch

    p, b, h = blender_rotation_to_msfs_pbh(rx, ry, rz)
    assert abs(p - 10.0) < 1e-3
    assert abs(b - 0.0) < 1e-3
    assert abs(h - 0.0) < 1e-3


def test_mirror_pbh_rotation_and_coords():
    """Verify sagittal reflection negates Heading/Bank and Lateral coords."""
    p_orig, b_orig, h_orig = (12.0, 5.0, 25.0)
    p_mir, b_mir, h_mir = mirror_pbh_rotation(p_orig, b_orig, h_orig)

    assert p_mir == p_orig
    assert b_mir == -b_orig
    assert h_mir == -h_orig

    long_orig, lat_orig, vert_orig = (-2.0, 16.4, 0.2)
    l_mir, lat_mir, v_mir = mirror_spatial_coords(long_orig, lat_orig, vert_orig)
    assert l_mir == long_orig
    assert lat_mir == -lat_orig
    assert v_mir == vert_orig


SYNTHETIC_SYSTEMS_CFG = """[VERSION]
major = 1
minor = 0

[LIGHTS]
lightdef.0 = Type:3#Index:0#LocalPosition:-2,16.4,0.2#LocalRotation:0,0,0#EffectFile:LIGHT_ASOBO_NavigationGreen#EmMesh:LIGHT_Nav_G
lightdef.1 = Type:3#Index:0#LocalPosition:-2,-16.4,0.2#LocalRotation:0,0,0#EffectFile:LIGHT_ASOBO_NavigationRed#EmMesh:LIGHT_Nav_R
lightdef.4 = Type:6#Index:1#LocalPosition:4,0,-2.2#LocalRotation:10,0,0#EffectFile:LIGHT_ASOBO_Landing

[ELECTRICAL]
bus.1 = Connections:bus.2#Name:BUS_1
circuit.1 = Type:CIRCUIT_GENERAL_PANEL#Name:General_Panel
"""


def test_parse_and_insert_lights():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".cfg", encoding="utf-8") as tf:
        tf.write(SYNTHETIC_SYSTEMS_CFG)
        tf_path = tf.name

    try:
        config = MSFSCSTParser.parse_file(tf_path)
        assert len(config.lights) == 3

        nav_green = config.get_point_by_id("LIGHTS:lightdef.0")
        assert nav_green is not None
        assert nav_green.coords_msfs_rel_ft == (-2.0, 16.4, 0.2)
        assert nav_green.em_mesh == "LIGHT_Nav_G"

        landing = config.get_point_by_id("LIGHTS:lightdef.4")
        assert landing is not None
        assert landing.rotation_pbh_deg == (10.0, 0.0, 0.0)

        # Test inserting a new mirrored taxi light into [LIGHTS]
        new_record = CFGLineRecord(
            raw_line="lightdef.5 = Type:6#Index:2#LocalPosition:4,2,-2.2#LocalRotation:5,0,0\n",
            section="LIGHTS",
            key="lightdef.5",
            coordinates=(4.0, 2.0, -2.2),
            rotation=(5.0, 0.0, 0.0),
            raw_tags={"Type": "6", "Index": "2", "LocalPosition": "4,2,-2.2", "LocalRotation": "5,0,0"},
            is_spatial=True,
        )
        insert_idx = MSFSCSTParser.insert_record_into_section(config, "LIGHTS", new_record, after_key="lightdef.4")
        assert insert_idx > 0

        # Save and verify file
        backup = MSFSCSTParser.serialize_and_save(config, updated_points={}, target_path=tf_path)
        assert os.path.exists(backup)

        with open(tf_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "lightdef.5 = Type:6#Index:2#LocalPosition:4,2,-2.2#LocalRotation:5,0,0" in content
        # Ensure electrical circuits below are completely intact
        assert "[ELECTRICAL]" in content
        assert "bus.1 = Connections:bus.2#Name:BUS_1" in content

        if os.path.exists(backup):
            os.remove(backup)
    finally:
        if os.path.exists(tf_path):
            os.remove(tf_path)


def test_parse_real_simpleaircraft_systems():
    sample_cfg = (
        r"C:\MSFS 2024 SDK\Samples\DevmodeProjects\SimObjects\Aircraft\SimpleAircraft"
        r"\PackageSources\SimObjects\Airplanes\MyCompany_Simple_Aircraft\common\config\systems.cfg"
    )
    if not os.path.isfile(sample_cfg):
        pytest.skip("MSFS 2024 SDK SimpleAircraft sample not installed on local machine")

    config = MSFSCSTParser.parse_file(sample_cfg)
    assert len(config.lights) == 5

    # Check Nav Green
    nav_g = config.get_point_by_id("LIGHTS:lightdef.0")
    assert nav_g is not None
    assert nav_g.light_type == 3
    assert nav_g.coords_msfs_rel_ft == (-2.0, 16.4, 0.2)
    assert nav_g.em_mesh == "LIGHT_Navigation_Green"

    # Check Landing
    landing = config.get_point_by_id("LIGHTS:lightdef.4")
    assert landing is not None
    assert landing.light_type == 6
    assert landing.rotation_pbh_deg == (10.0, 0.0, 0.0)
