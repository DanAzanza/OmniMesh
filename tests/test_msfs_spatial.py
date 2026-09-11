"""
Automated Pytest Suite for MSFS Spatial Configuration Pipeline.
Tests mathematical transformations, CST lossless parsing, MSFS 2020 vs 2024 syntax,
comment preservation, and atomic backup serialization.
"""

from __future__ import annotations

import os
import tempfile
import pytest

from core.msfs_cst_parser import MSFSCSTParser
from core.msfs_transforms import (
    FEET_TO_METERS,
    blender_to_msfs,
    format_coordinate_float,
    msfs_to_blender,
)


def test_msfs_transforms_basic():
    datum = (3.6, 0.0, 0.0)  # SimpleAircraft datum: long=3.6, lat=0, vert=0 (ft)
    nose_gear_rel = (4.0, 0.0, -4.45)  # point.0 (ft)

    # 1. Transform to Blender (m)
    blender_x, blender_y, blender_z = msfs_to_blender(nose_gear_rel[0], nose_gear_rel[1], nose_gear_rel[2], datum)

    # Expected:
    # Lat=0 -> Blender X = 0.0
    # Long=4.0 + 3.6 = 7.6 ft -> Blender Y = 7.6 * 0.3048 = 2.31648 m
    # Vert=-4.45 ft -> Blender Z = -4.45 * 0.3048 = -1.35636 m
    assert abs(blender_x - 0.0) < 1e-6
    assert abs(blender_y - (7.6 * FEET_TO_METERS)) < 1e-6
    assert abs(blender_z - (-4.45 * FEET_TO_METERS)) < 1e-6

    # 2. Invert back to MSFS relative feet
    res_long, res_lat, res_vert = blender_to_msfs(blender_x, blender_y, blender_z, datum)
    assert abs(res_long - nose_gear_rel[0]) < 1e-6
    assert abs(res_lat - nose_gear_rel[1]) < 1e-6
    assert abs(res_vert - nose_gear_rel[2]) < 1e-6


def test_msfs_transforms_lateral_and_vertical():
    datum = (10.0, 2.0, -1.0)
    pt_rel = (-5.5, 12.0, 3.2)

    bx, by, bz = msfs_to_blender(pt_rel[0], pt_rel[1], pt_rel[2], datum)

    # Lat: 12 + 2 = 14 ft -> bx
    assert abs(bx - 14.0 * FEET_TO_METERS) < 1e-6
    # Long: -5.5 + 10 = 4.5 ft -> by
    assert abs(by - 4.5 * FEET_TO_METERS) < 1e-6
    # Vert: 3.2 - 1.0 = 2.2 ft -> bz
    assert abs(bz - 2.2 * FEET_TO_METERS) < 1e-6

    rev_long, rev_lat, rev_vert = blender_to_msfs(bx, by, bz, datum)
    assert abs(rev_long - pt_rel[0]) < 1e-6
    assert abs(rev_lat - pt_rel[1]) < 1e-6
    assert abs(rev_vert - pt_rel[2]) < 1e-6


def test_format_coordinate_float():
    assert format_coordinate_float(4.0) == "4"
    assert format_coordinate_float(4.5) == "4.5"
    assert format_coordinate_float(-7.600) == "-7.6"
    assert format_coordinate_float(0.0000001) == "0"
    assert format_coordinate_float(-0.0) == "0"
    assert format_coordinate_float(1.23456) == "1.2346"


SYNTHETIC_CFG_MSFS2024 = """[VERSION]
major = 1
minor = 0

[WEIGHT_AND_BALANCE]
reference_datum_position = 3.6, 0, 0 ; Datum offset
empty_weight_CG_position = -4, 0, 0.2 ; CG offset

[CONTACT_POINTS]
static_pitch = 0 ; Pitch angle
point.0 = Name:NoseWheel#Properties:1, 4.0, 0.0, -4.45, 720, 0, 0.62, 22 ; Front
point.1 = Name:MainLeft#Properties:1, -4.8, -7.6, -4.45, 1500, 1, 0.79 ; Gear L
point.2 = Name:MainRight#Properties:1, -4.8, 7.6, -4.45, 1500, 2, 0.79 ; Gear R

[FUEL]
LeftMain = -5, -4.5, -0.2, 37, 3 ; Left wing tank
RightMain = -5, 4.5, -0.2, 37, 3 ; Right wing tank
fuel_type = 1
"""


def test_cst_parser_msfs2024():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".cfg", encoding="utf-8") as tf:
        tf.write(SYNTHETIC_CFG_MSFS2024)
        tf_path = tf.name

    try:
        config = MSFSCSTParser.parse_file(tf_path)

        assert config.reference_datum_ft == (3.6, 0.0, 0.0)
        assert config.empty_weight_cg_ft == (-4.0, 0.0, 0.2)

        p0 = config.get_point_by_id("CONTACT_POINTS:point.0")
        assert p0 is not None
        assert p0.name_tag == "NoseWheel"
        assert p0.point_class == 1
        assert p0.coords_msfs_rel_ft == (4.0, 0.0, -4.45)
        # Blender Y should be (4.0 + 3.6) * 0.3048 = 2.31648
        assert abs(p0.coords_blender_m[1] - 2.31648) < 1e-4

        fuel_l = config.get_point_by_id("FUEL:LeftMain")
        assert fuel_l is not None
        assert fuel_l.coords_msfs_rel_ft == (-5.0, -4.5, -0.2)

        # Test sync with modified coordinates
        updated = {
            "CONTACT_POINTS:point.0": (4.5, 0.0, -4.5),  # moved nose gear
        }
        backup = MSFSCSTParser.serialize_and_save(config, updated)

        assert os.path.exists(backup)
        with open(tf_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check that modified line changed properly with prefix and comment intact
        assert "point.0 = Name:NoseWheel#Properties:1, 4.5, 0, -4.5, 720, 0, 0.62, 22 ; Front" in content
        # Check that unedited lines and comments are intact
        assert "point.1 = Name:MainLeft#Properties:1, -4.8, -7.6, -4.45, 1500, 1, 0.79 ; Gear L" in content
        assert "static_pitch = 0 ; Pitch angle" in content
        assert "fuel_type = 1" in content

        if os.path.exists(backup):
            os.remove(backup)
    finally:
        if os.path.exists(tf_path):
            os.remove(tf_path)


SYNTHETIC_CFG_MSFS2020 = """[WEIGHT_AND_BALANCE]
reference_datum_position = 0, 0, 0

[CONTACT_POINTS]
point.0 = 1, 3.5, 0, -3.2, 500, 0, 0.5, 20
point.1 = 1, -2.0, -5.0, -3.2, 1000, 1, 0.6, 0

[FUEL]
Center1 = 0, 0, 0, 50, 2
"""


def test_cst_parser_msfs2020_classic():
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".cfg", encoding="utf-8") as tf:
        tf.write(SYNTHETIC_CFG_MSFS2020)
        tf_path = tf.name

    try:
        config = MSFSCSTParser.parse_file(tf_path)
        p0 = config.get_point_by_id("CONTACT_POINTS:point.0")
        assert p0 is not None
        assert p0.coords_msfs_rel_ft == (3.5, 0.0, -3.2)
        assert p0.point_class == 1

        updated = {"CONTACT_POINTS:point.0": (3.8, 0.0, -3.1)}
        backup = MSFSCSTParser.serialize_and_save(config, updated)

        with open(tf_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "point.0 = 1, 3.8, 0, -3.1, 500, 0, 0.5, 20" in content
        if os.path.exists(backup):
            os.remove(backup)
    finally:
        if os.path.exists(tf_path):
            os.remove(tf_path)


def test_parse_real_simpleaircraft_sample():
    sample_cfg = (
        r"C:\MSFS 2024 SDK\Samples\DevmodeProjects\SimObjects\Aircraft\SimpleAircraft"
        r"\PackageSources\SimObjects\Airplanes\MyCompany_Simple_Aircraft\common\config\flight_model.cfg"
    )
    if not os.path.isfile(sample_cfg):
        pytest.skip("MSFS 2024 SDK SimpleAircraft sample not installed on local machine")

    config = MSFSCSTParser.parse_file(sample_cfg)
    assert config.reference_datum_ft == (3.6, 0.0, 0.0)

    # SimpleAircraft has 10 contact points (point.0 to point.9)
    contact_points = [p for p in config.points if p.section == "CONTACT_POINTS"]
    assert len(contact_points) == 10

    # Fuel tanks
    fuel_tanks = [p for p in config.points if p.section == "FUEL"]
    assert len(fuel_tanks) >= 2
