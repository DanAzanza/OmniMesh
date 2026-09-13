"""
Automated Pytest Suite for OmniMesh Multi-Engine Animation Manager.
Verifies Action and NLA track discovery, semantic category tagging,
deterministic GUID generation, and MSFS ModelInfo XML block synthesis.
"""

from __future__ import annotations

from unittest.mock import MagicMock


import core.animation_manager as am
from core.animation_manager import (
    build_msfs_animation_xml_block,
    scan_asset_animations,
    tag_action_category,
)


# =============================================================================
# ACTION DISCOVERY & TAGGING TESTS
# =============================================================================


class MockAction:
    def __init__(self, name: str, frame_range: tuple[float, float] = (0.0, 120.0)):
        self.name = name
        self.frame_range = frame_range
        self.custom_props: dict[str, any] = {}

    def __setitem__(self, key: str, value: any):
        self.custom_props[key] = value

    def __getitem__(self, key: str):
        return self.custom_props[key]

    def __contains__(self, key: str) -> bool:
        return key in self.custom_props

    def get(self, key: str, default: any = None):
        return self.custom_props.get(key, default)


def test_scan_asset_animations_active_action_and_nla(monkeypatch):
    """Verify scanning captures both active actions and NLA track strips."""
    gear_act = MockAction("Gear_Retract", (0.0, 200.0))
    rudder_act = MockAction("Rudder_Deflection", (0.0, 50.0))

    armature = MagicMock()
    armature.name = "Aircraft_Armature"
    armature.animation_data.action = gear_act

    strip = MagicMock()
    strip.action = rudder_act
    track = MagicMock()
    track.strips = [strip]
    armature.animation_data.nla_tracks = [track]

    root_coll = MagicMock()
    root_coll.all_objects = [armature]

    mock_bpy = MagicMock()
    mock_bpy.data.collections.get.return_value = root_coll
    monkeypatch.setattr(am, "bpy", mock_bpy)

    ctx = MagicMock()
    actions = scan_asset_animations(ctx, "Aircraft")

    assert len(actions) == 2
    act_names = [a["name"] for a in actions]
    assert "Gear_Retract" in act_names
    assert "Rudder_Deflection" in act_names

    gear_info = next(a for a in actions if a["name"] == "Gear_Retract")
    assert gear_info["start_frame"] == 0
    assert gear_info["end_frame"] == 200
    assert gear_info["length"] == 200
    assert len(gear_info["guid"]) > 0


def test_tag_action_category(monkeypatch):
    """Verify tag_action_category updates semantic category and deterministic GUID."""
    mock_act = MockAction("Elevator_Trim")
    mock_bpy = MagicMock()
    mock_bpy.data.actions.get.side_effect = lambda name: mock_act if name == "Elevator_Trim" else None
    monkeypatch.setattr(am, "bpy", mock_bpy)

    success = tag_action_category("Elevator_Trim", "FLIGHT_CONTROL")
    assert success is True
    assert mock_act["_omnimesh_category"] == "FLIGHT_CONTROL"
    assert "_omnimesh_guid" in mock_act
    guid1 = mock_act["_omnimesh_guid"]

    # Assign custom GUID
    success_custom = tag_action_category(
        "Elevator_Trim", "FLIGHT_CONTROL", custom_guid="11111111-2222-3333-4444-555555555555"
    )
    assert success_custom is True
    assert mock_act["_omnimesh_guid"] == "11111111-2222-3333-4444-555555555555"
    assert mock_act["_omnimesh_guid"] != guid1


# =============================================================================
# MSFS MODELINFO XML GENERATION TESTS
# =============================================================================


def test_build_msfs_animation_xml_block():
    """Verify generation of compliant MSFS <Animation> and <PartInfo> XML structures."""
    actions = [
        {
            "name": "Landing_Gear_Deploy",
            "sanitized_name": "Landing_Gear_Deploy",
            "guid": "abcdef01-2345-6789-abcd-ef0123456789",
            "length": 150,
            "category": "LANDING_GEAR",
        },
        {
            "name": "Cockpit_Door_Open",
            "sanitized_name": "Cockpit_Door_Open",
            "guid": "12345678-abcd-ef01-2345-6789abcdef01",
            "length": 60,
            "category": "DOOR",
        },
    ]

    anim_xml, part_xml = build_msfs_animation_xml_block(actions)

    # <Animation> block validation
    assert "<Animation>" in anim_xml
    assert "</Animation>" in anim_xml
    assert 'name="Landing_Gear_Deploy"' in anim_xml
    assert 'guid="abcdef01-2345-6789-abcd-ef0123456789"' in anim_xml
    assert 'length="150"' in anim_xml
    assert 'type="Sim"' in anim_xml
    assert 'typeParam="AutoPlay"' in anim_xml

    # <PartInfo> block validation
    assert "<PartInfo>" in part_xml
    assert "<Name>Landing_Gear_Deploy</Name>" in part_xml
    assert "<AnimLength>150</AnimLength>" in part_xml
    assert "<Variable>GEAR TOTAL PCT EXTENDED</Variable>" in part_xml
    assert "<Name>Cockpit_Door_Open</Name>" in part_xml
    assert "<Variable>CANOPY OPEN</Variable>" in part_xml
