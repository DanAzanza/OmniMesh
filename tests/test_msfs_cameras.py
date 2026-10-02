"""Unit tests for MSFS Cameras Pipeline (Phase 3)."""

import math
import os
import pytest

from core.msfs.camera_cst import MSFSCameraCST, detect_file_format
from core.msfs.cst_parser import MSFSCSTParser
from core.msfs.models import CameraDefinition
from core.msfs.transforms import (
    blender_focal_length_to_msfs_zoom,
    blender_rotation_to_msfs_pbh,
    msfs_pbh_to_blender_rotation,
    msfs_zoom_to_blender_focal_length,
)


def test_camera_pbh_roundtrip_coupled_angles():
    """Verify exact closed-form PBH decomposition for complex coupled pitch, bank, and heading."""
    # Test cases: (pitch, bank, heading) in degrees
    cases = [
        (0.0, 0.0, 0.0),
        (20.0, 0.0, 0.0),
        (0.0, 15.0, 0.0),
        (0.0, 0.0, 45.0),
        (-25.0, 10.0, 60.0),
        (15.0, -18.0, -85.0),
        (35.0, 25.0, 120.0),
    ]

    for p_in, b_in, h_in in cases:
        rx, ry, rz = msfs_pbh_to_blender_rotation(p_in, b_in, h_in)
        p_out, b_out, h_out = blender_rotation_to_msfs_pbh(rx, ry, rz)

        assert abs(p_out - p_in) < 1e-3, f"Pitch mismatch for input ({p_in}, {b_in}, {h_in}): got {p_out}"
        assert abs(b_out - b_in) < 1e-3, f"Bank mismatch for input ({p_in}, {b_in}, {h_in}): got {b_out}"
        assert abs(h_out - h_in) < 1e-3, f"Heading mismatch for input ({p_in}, {b_in}, {h_in}): got {h_out}"


def test_camera_optics_conversions():
    """Verify bidirectional conversion between MSFS InitialZoom and Blender focal length."""
    assert msfs_zoom_to_blender_focal_length(1.0) == 35.0
    assert msfs_zoom_to_blender_focal_length(0.5) == 17.5
    assert msfs_zoom_to_blender_focal_length(2.0) == 70.0

    # Inversion
    assert blender_focal_length_to_msfs_zoom(35.0) == 1.0
    assert blender_focal_length_to_msfs_zoom(17.5) == 0.5
    assert blender_focal_length_to_msfs_zoom(70.0) == 2.0


def test_parse_synthetic_cameras_cfg(tmp_path):
    """Verify parsing and serialization of a synthetic cameras.cfg with contiguous indexing."""
    raw_cfg = """[VERSION]
major = 1
minor = 0

[VIEWS]
eyepoint = -3.95, -0.85, 1.9 ; (feet) longitudinal, lateral, vertical distance from reference datum

[CAMERADEFINITION.0]
Title = "Pilot"
Guid = "{195EAB58-9E4A-1E2A-A34C-A8D9D948F078}"
Origin = "Virtual Cockpit"
Category = "Cockpit"
SubCategory = "Pilot"
InitialZoom = 0.57
InitialXyz = 0.05, 0.22, 0.05
InitialPbh = -3, 0, 0

[CAMERADEFINITION.1]
Title = "FixedOnPlane_Tail"
Guid = "{8A6AA746-50B1-43BD-A51C-31A9FBBFCB94}"
Origin = "Center"
Category = "FixedOnPlane"
SubCategory = "FixedOnPlaneExtern"
InitialZoom = 1.3
InitialXyz = 0, 2.15, -5
InitialPbh = -27.5, 0, 0
"""
    cfg_file = tmp_path / "cameras.cfg"
    cfg_file.write_text(raw_cfg, encoding="utf-8")

    config = MSFSCSTParser.parse_cameras_file(str(cfg_file))

    assert config.eyepoint_ft == (-3.95, -0.85, 1.9)
    assert len(config.cameras) == 2

    pilot = config.cameras[0]
    assert pilot.title == "Pilot"
    assert pilot.guid == "{195EAB58-9E4A-1E2A-A34C-A8D9D948F078}"
    assert pilot.origin == "Virtual Cockpit"
    assert pilot.category == "Cockpit"
    assert pilot.subcategory == "Pilot"
    assert pilot.initial_zoom == 0.57
    assert pilot.initial_xyz_m == (0.05, 0.22, 0.05)
    assert pilot.initial_pbh_deg == (-3.0, 0.0, 0.0)

    tail = config.cameras[1]
    assert tail.title == "FixedOnPlane_Tail"
    assert tail.origin == "Center"
    assert tail.category == "FixedOnPlane"
    assert tail.initial_xyz_m == (0.0, 2.15, -5.0)


def test_serialize_cameras_gapless_and_backup(tmp_path):
    """Verify serialize_and_save_cameras enforces gapless indexing and generates preflight backup."""
    raw_cfg = """[VERSION]
major = 1
minor = 0

[VIEWS]
eyepoint = -3.95, -0.85, 1.9

[CAMERADEFINITION.0]
Title = "Pilot"
Guid = "{195EAB58-9E4A-1E2A-A34C-A8D9D948F078}"
Origin = "Virtual Cockpit"
Category = "Cockpit"
SubCategory = "Pilot"
InitialZoom = 0.57
InitialXyz = 0.05, 0.22, 0.05
InitialPbh = -3, 0, 0
"""
    cfg_file = tmp_path / "cameras.cfg"
    cfg_file.write_text(raw_cfg, encoding="utf-8")

    config = MSFSCSTParser.parse_cameras_file(str(cfg_file))

    # Add a second camera with out-of-order index to test contiguous re-indexing
    new_cam = CameraDefinition(
        index=99,
        title="Copilot",
        guid="{AAAA-BBBB-CCCC-DDDD}",
        origin="Virtual Cockpit",
        category="Cockpit",
        subcategory="Pilot",
        initial_zoom=0.6,
        initial_xyz_m=(0.5, 0.22, 0.05),
        initial_pbh_deg=(-5.0, 0.0, 0.0),
    )
    config.cameras.append(new_cam)

    backup_path = MSFSCSTParser.serialize_and_save_cameras(config, target_path=str(cfg_file))

    assert os.path.exists(backup_path)

    re_parsed = MSFSCSTParser.parse_cameras_file(str(cfg_file))
    assert len(re_parsed.cameras) == 2
    assert re_parsed.cameras[0].index == 0
    assert re_parsed.cameras[1].index == 1  # Re-indexed gaplessly from 99 to 1
    assert re_parsed.cameras[1].title == "Copilot"


def test_parse_real_simpleaircraft_cameras():
    """Verify parsing real MSFS 2024 SDK SimpleAircraft cameras.cfg (910 lines, 29 cameras)."""
    real_path = r"C:\MSFS 2024 SDK\Samples\DevmodeProjects\SimObjects\Aircraft\SimpleAircraft\PackageSources\SimObjects\Airplanes\MyCompany_Simple_Aircraft\common\config\cameras.cfg"
    if not os.path.isfile(real_path):
        pytest.skip("MSFS 2024 SDK SimpleAircraft samples not found on system.")

    config = MSFSCSTParser.parse_cameras_file(real_path)

    assert config.eyepoint_ft[0] == pytest.approx(-3.95, rel=1e-3)
    assert len(config.cameras) >= 28

    # Camera 0 must be Pilot
    cam0 = config.cameras[0]
    assert cam0.title == "Pilot"
    assert cam0.category == "Cockpit"
    assert cam0.subcategory == "Pilot"
    assert cam0.origin == "Virtual Cockpit"

    # Verify an external camera (e.g. Tail or Wing)
    tail_cam = next((c for c in config.cameras if "Tail" in c.title), None)
    assert tail_cam is not None
    assert tail_cam.origin == "Center"
    assert tail_cam.category == "FixedOnPlane"


def test_msfs_cst_parser_keys_with_spaces(tmp_path):
    """Verify MSFSCSTParser parses keys containing embedded spaces."""
    cfg_content = (
        "[CAMERADEFINITION.0]\n"
        'Title = "Pilot View"\n'
        "Initial Zoom = 0.35\n"
        'SubCategory Title = "Cockpit"\n'
        "Initial Xyz = 0.0, 1.2, -0.5\n"
    )
    test_file = tmp_path / "cameras_test.cfg"
    test_file.write_text(cfg_content, encoding="utf-8")

    config = MSFSCSTParser.parse_file(str(test_file))
    assert len(config.lines) >= 5

    parsed_keys = [record.key for record in config.lines if record.key]
    assert "Title" in parsed_keys
    assert "Initial Zoom" in parsed_keys
    assert "SubCategory Title" in parsed_keys
    assert "Initial Xyz" in parsed_keys


def test_camera_cst_key_normalization(tmp_path):
    """Verify camera CST normalizes keys with spaces and underscores."""
    cfg_content = (
        "[CAMERADEFINITION.0]\n"
        'Title = "Cockpit Center"\n'
        "Initial Zoom = 0.45\n"
        'SubCategory Title = "Quickview"\n'
        "Initial Xyz = 0.1, 0.8, -0.2\n"
        "Initial Pbh = 5.0, 0.0, 0.0\n"
    )
    test_file = tmp_path / "cameras_norm.cfg"
    test_file.write_text(cfg_content, encoding="utf-8")

    cam_config = MSFSCameraCST.parse_cameras_file(str(test_file))
    assert len(cam_config.cameras) == 1
    cam = cam_config.cameras[0]
    assert cam.title == "Cockpit Center"
    assert math.isclose(cam.initial_zoom, 0.45, rel_tol=1e-5)
    assert cam.subcategory == "Quickview"
    assert cam.initial_xyz_m == (0.1, 0.8, -0.2)
    assert cam.initial_pbh_deg == (5.0, 0.0, 0.0)


def test_detect_file_format_encodings(tmp_path):
    """Verify detect_file_format handles UTF-8, UTF-8 BOM, UTF-16 LE, and CP1252."""
    # 1. UTF-8 standard
    f_utf8 = tmp_path / "utf8.txt"
    f_utf8.write_bytes(b"sample content\n")
    enc, bom, nl = detect_file_format(str(f_utf8))
    assert enc == "utf-8"
    assert bom is False
    assert nl == "\n"

    # 2. UTF-8 with BOM
    f_utf8_bom = tmp_path / "utf8_bom.txt"
    f_utf8_bom.write_bytes(b"\xef\xbb\xbfsample with bom\r\n")
    enc, bom, nl = detect_file_format(str(f_utf8_bom))
    assert enc == "utf-8-sig"
    assert bom is True
    assert nl == "\r\n"

    # 3. UTF-16 LE with BOM
    f_utf16 = tmp_path / "utf16_le.txt"
    f_utf16.write_bytes(b"\xff\xfe" + "flight config".encode("utf-16-le"))
    enc, bom, nl = detect_file_format(str(f_utf16))
    assert enc == "utf-16-le"
    assert bom is True

    # 4. CP1252 (invalid UTF-8 bytes)
    f_cp1252 = tmp_path / "cp1252.txt"
    f_cp1252.write_bytes(b"Caf\xe9 au lait\n")
    enc, bom, nl = detect_file_format(str(f_cp1252))
    assert enc == "cp1252"
    assert bom is False
