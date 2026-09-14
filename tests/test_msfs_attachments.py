"""
Comprehensive Automated Tests for MSFS 2024 Modular Attachments & Submodels Subsystem.
Validates:
1. Lossless parsing of attached_objects.cfg
2. CST build_new_config synthesis from scratch
3. Local node-relative kinematics and offset extraction
4. Dedicated empty Euler rotation vs PBH aerospace conventions
5. Atomic serialization with automatic timestamped backup
"""

import math
import os
import tempfile

from core.msfs.attachments_cst import MSFSAttachmentsCST
from core.msfs.models import SimAttachmentPoint
from core.msfs.transforms import (
    blender_empty_rotation_to_msfs_pbh,
    msfs_pbh_to_blender_empty_rotation,
)


CABRI_G2_ATTACHMENTS_SAMPLE = """[VERSION]
major = 1
minor = 0

[merge_model.0]
node = "ATTACH_POINT_MAGNETO"
model = "SimAttachments/Instruments/Bendix_King_Magneto.xml"

[merge_model.1]
node = "ATTACH_POINT_ROTOR_TACH"
model = "SimAttachments/Instruments/Cabri_G2_Tachometer.xml"

[sim_attachment.0]
attachment_root = "SimAttachments/Instruments"
attachment = "SimAttachments/Instruments/Bendix_King_Magneto.xml"
attach_to_model = "Interior"
attach_to_node = "ATTACH_POINT_MAGNETO"
attach_offset = 0.05, -0.12, 0.45 ; long, lat, vert in feet
attach_pbh = 5.0, -2.5, 90.0 ; pitch, bank, heading in deg
alias = "MagnetoSwitch"
attach_scale = 1.0

[sim_attachment.1]
attachment_root = "SimAttachments/Equipment"
attachment = "SimAttachments/Equipment/Fire_Extinguisher.xml"
attach_to_model = "Interior"
attach_to_node = "ATTACH_POINT_EXTINGUISHER"
attach_offset = 0.0, 0.0, 0.0
attach_pbh = 0.0, 0.0, 0.0
alias = "Extinguisher"
attach_scale = 1.0
"""


def test_parse_attached_objects_cfg():
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".cfg", delete=False) as f:
        f.write(CABRI_G2_ATTACHMENTS_SAMPLE)
        temp_path = f.name

    try:
        cfg = MSFSAttachmentsCST.parse_attachments_file(temp_path)
        assert cfg.version_major == 1
        assert cfg.version_minor == 0
        assert len(cfg.merge_models) == 2
        assert cfg.merge_models[0]["node"] == "ATTACH_POINT_MAGNETO"
        assert len(cfg.attachments) == 2

        att0 = cfg.attachments[0]
        assert att0.alias == "MagnetoSwitch"
        assert att0.attach_to_node == "ATTACH_POINT_MAGNETO"
        assert att0.attach_to_model == "Interior"
        assert att0.attach_offset_ft == (0.05, -0.12, 0.45)
        assert att0.attach_pbh_deg == (5.0, -2.5, 90.0)

        att1 = cfg.attachments[1]
        assert att1.alias == "Extinguisher"
        assert att1.attach_offset_ft == (0.0, 0.0, 0.0)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_empty_rotation_pbh_roundtrip():
    """Verify generic empty rotation without lamp basis offset roundtrips accurately."""
    test_cases = [
        (0.0, 0.0, 0.0),
        (15.0, 0.0, 0.0),
        (0.0, -20.0, 0.0),
        (0.0, 0.0, 45.0),
        (-10.5, 25.0, 135.0),
        (30.0, -15.0, -90.0),
    ]

    for p_in, b_in, h_in in test_cases:
        rx, ry, rz = msfs_pbh_to_blender_empty_rotation(p_in, b_in, h_in)
        p_out, b_out, h_out = blender_empty_rotation_to_msfs_pbh(rx, ry, rz)
        assert math.isclose(p_in, p_out, abs_tol=1e-3), f"Pitch mismatch for {(p_in, b_in, h_in)}: got {p_out}"
        assert math.isclose(b_in, b_out, abs_tol=1e-3), f"Bank mismatch for {(p_in, b_in, h_in)}: got {b_out}"
        # Normalize heading diff
        h_diff = (h_in - h_out + 180.0) % 360.0 - 180.0
        assert abs(h_diff) < 1e-3, f"Heading mismatch for {(p_in, b_in, h_in)}: got {h_out}"


def test_build_new_config_synthesis():
    """Verify creating an attached_objects.cfg from scratch when none exists."""
    att0 = SimAttachmentPoint(
        point_id="ATTACHMENTS:sim_attachment.0",
        section="sim_attachment.0",
        key="sim_attachment.0",
        point_type="ATTACHMENT",
        attachment_path="SimAttachments/Garmin/G1000_PFD.xml",
        attachment_root="SimAttachments/Garmin",
        attach_to_model="Interior",
        attach_to_node="ATTACH_POINT_G1000",
        alias="G1000_PFD",
        attach_scale=1.0,
        attach_offset_ft=(0.1, -0.2, 0.3),
        attach_pbh_deg=(0.0, 0.0, 0.0),
    )

    merge0 = {
        "node": "ATTACH_POINT_G1000",
        "model": "SimAttachments/Garmin/G1000_PFD.xml",
    }

    config = MSFSAttachmentsCST.build_new_config(
        attachments=[att0],
        merge_models=[merge0],
        version_major=1,
        version_minor=0,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        dest_path = os.path.join(tmpdir, "config", "attached_objects.cfg")
        MSFSAttachmentsCST.serialize_and_save(config=config, target_path=dest_path)

        assert os.path.isfile(dest_path)
        with open(dest_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "[VERSION]" in content
        assert "major = 1" in content
        assert "[merge_model.0]" in content
        assert 'node = "ATTACH_POINT_G1000"' in content
        assert "[sim_attachment.0]" in content
        assert 'alias = "G1000_PFD"' in content
        assert "attach_offset = 0.1, -0.2, 0.3" in content


def test_atomic_serialize_and_update_with_backup():
    """Verify modifying offsets and rotations serializes with automatic backup."""
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".cfg", delete=False) as f:
        f.write(CABRI_G2_ATTACHMENTS_SAMPLE)
        temp_path = f.name

    try:
        config = MSFSAttachmentsCST.parse_attachments_file(temp_path)
        updated_pts = {
            "ATTACHMENTS:sim_attachment.0": (1.23, -4.56, 7.89),
        }
        updated_rots = {
            "ATTACHMENTS:sim_attachment.0": (12.0, -3.0, 180.0),
        }

        backup_file = MSFSAttachmentsCST.serialize_and_save(
            config=config,
            updated_points=updated_pts,
            updated_rotations=updated_rots,
            target_path=temp_path,
        )

        assert os.path.isfile(backup_file)
        with open(temp_path, "r", encoding="utf-8") as f:
            updated_content = f.read()

        assert "attach_offset = 1.23, -4.56, 7.89" in updated_content
        assert "attach_pbh = 12, -3, 180" in updated_content
        # Ensure comments and second attachment remain intact
        assert "; long, lat, vert in feet" in updated_content
        assert 'alias = "Extinguisher"' in updated_content

        if os.path.exists(backup_file):
            os.remove(backup_file)

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
