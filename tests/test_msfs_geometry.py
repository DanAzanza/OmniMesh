"""Unit tests for MSFS Geometry Detection & Ground Alignment (Phase 2)."""

import os

import numpy as np
import pytest

from core.msfs_cst_parser import MSFSCSTParser
from core.msfs_geometry import (
    detect_airframe_extrema,
    format_class_2_scrape_tokens,
    is_structural_airframe_object,
)


def test_is_structural_airframe_object():
    """Verify semantic object filtering rules."""
    assert is_structural_airframe_object("Fuselage_LOD0") is True
    assert is_structural_airframe_object("Wing_Left_Main") is True
    assert is_structural_airframe_object("Vertical_Fin") is True

    # Excluded items
    assert is_structural_airframe_object("Propeller_Blade_01") is False
    assert is_structural_airframe_object("Engine_Spinner") is False
    assert is_structural_airframe_object("Antenna_VHF_Belly") is False
    assert is_structural_airframe_object("Static_Wick_L") is False
    assert is_structural_airframe_object("Cockpit_Interior") is False
    assert is_structural_airframe_object("Pilot_Body") is False
    assert is_structural_airframe_object("Collider_Hull") is False


def test_detect_airframe_extrema():
    """Verify airframe extrema detection on synthetic point cloud."""
    # Synthetic aircraft coordinates in Blender meters:
    # X: Lateral (-5 to +5), Y: Long (-6 to +4), Z: Vert (-1 to +2)
    verts = np.array(
        [
            # Left wingtip
            [-5.0, 0.0, 0.5],
            # Right wingtip
            [5.0, 0.0, 0.5],
            # Nose (foremost, on centerline)
            [0.0, 4.0, 0.0],
            # Tail (aftmost, on centerline)
            [0.0, -6.0, 0.2],
            # Keel (lowest, on centerline)
            [0.0, 0.0, -1.0],
            # Fin (highest, aft centerline)
            [0.0, -5.5, 2.2],
            # Center body fill points
            [0.1, 1.0, 0.0],
            [-0.1, -1.0, 0.0],
            [1.0, 0.0, 0.1],
            [-1.0, 0.0, 0.1],
        ],
        dtype=np.float32,
    )

    extrema = detect_airframe_extrema(verts, fuselage_width_tol_m=0.4)

    assert "Scrape_Wing_L" in extrema
    assert "Scrape_Wing_R" in extrema
    assert "Scrape_Nose" in extrema
    assert "Scrape_Tail" in extrema
    assert "Scrape_Keel" in extrema
    assert "Scrape_Fin" in extrema

    # Left wingtip: X = -5.0
    assert pytest.approx(extrema["Scrape_Wing_L"][0], rel=1e-2) == -5.0
    # Right wingtip: X = +5.0
    assert pytest.approx(extrema["Scrape_Wing_R"][0], rel=1e-2) == 5.0
    # Nose: Y = +4.0
    assert pytest.approx(extrema["Scrape_Nose"][1], rel=1e-2) == 4.0
    # Tail: Y = -6.0
    assert pytest.approx(extrema["Scrape_Tail"][1], rel=1e-2) == -6.0
    # Keel: Z = -1.0
    assert pytest.approx(extrema["Scrape_Keel"][2], rel=1e-2) == -1.0
    # Fin: Z = 2.2
    assert pytest.approx(extrema["Scrape_Fin"][2], rel=1e-2) == 2.2


def test_format_class_2_scrape_tokens():
    """Verify 16-parameter Class 2 schema formatting and margin adjustment."""
    coords_ft = (12.5, -16.4, -2.1)
    tokens = format_class_2_scrape_tokens("Scrape_Wing_L", coords_ft, margin_ft=0.5)

    assert len(tokens) == 16
    assert tokens[0] == "2"  # Class 2
    assert tokens[1] == "12.50"  # Longitude unchanged
    assert tokens[2] == "-16.90"  # Wing_L expanded outward (more negative)
    assert tokens[3] == "-2.10"  # Vertical unchanged
    assert tokens[4] == "1500.0"  # Crash speed


def test_update_scalar_param_existing(tmp_path):
    """Verify MSFSCSTParser.update_scalar_param updates an existing scalar losslessly."""
    cfg_content = """[CONTACT_POINTS]
static_pitch = 0.0
static_cg_height = 4.45 ; In feet
tailwheel_lock = 0
"""
    cfg_path = tmp_path / "flight_model.cfg"
    cfg_path.write_text(cfg_content, encoding="utf-8")

    config = MSFSCSTParser.parse_file(str(cfg_path))
    backup = MSFSCSTParser.update_scalar_param(
        config=config,
        section="CONTACT_POINTS",
        key="static_cg_height",
        value_str="5.12",
        output_path=cfg_path,
    )

    assert os.path.exists(backup)
    new_content = cfg_path.read_text(encoding="utf-8")
    assert "static_cg_height = 5.12 ; In feet" in new_content
    assert "static_pitch = 0.0" in new_content
    assert "tailwheel_lock = 0" in new_content


def test_update_scalar_param_new(tmp_path):
    """Verify MSFSCSTParser.update_scalar_param inserts scalar if key did not exist."""
    cfg_content = """[CONTACT_POINTS]
static_pitch = 0.0
"""
    cfg_path = tmp_path / "flight_model.cfg"
    cfg_path.write_text(cfg_content, encoding="utf-8")

    config = MSFSCSTParser.parse_file(str(cfg_path))
    MSFSCSTParser.update_scalar_param(
        config=config,
        section="CONTACT_POINTS",
        key="static_cg_height",
        value_str="4.80",
        output_path=cfg_path,
    )

    new_content = cfg_path.read_text(encoding="utf-8")
    assert "static_cg_height = 4.80" in new_content
    assert "static_pitch = 0.0" in new_content
