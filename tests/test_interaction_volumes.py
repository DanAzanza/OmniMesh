"""
Automated Pytest Suite for OmniMesh Interaction Volumes & Clickspots.
Verifies engine naming schemes, trigger geometry generation (Box/Sphere/Cylinder),
collection hierarchy routing, and non-blocking physics semantics.
"""

from __future__ import annotations

from unittest.mock import MagicMock


import core.interaction_volumes as iv
from core.interaction_volumes import (
    create_interaction_volume,
    get_engine_interaction_name,
)


# =============================================================================
# ENGINE NAMING TESTS
# =============================================================================


def test_engine_interaction_naming_schemes():
    """Verify engine-specific naming conventions guarantee trigger semantics."""
    asset = "Cessna172"
    role = "BUTTON"
    name = "MasterBattery"

    # MSFS MouseRect collider
    msfs_name = get_engine_interaction_name(asset, role, name, "MSFS")
    assert msfs_name == "Collision_BUTTON_MasterBattery"

    # Unreal non-blocking trigger (never UCX_)
    ue_name = get_engine_interaction_name(asset, role, name, "UNREAL")
    assert ue_name == "INTERACT_BUTTON_MasterBattery"
    assert not ue_name.startswith("UCX_")

    # Godot Area3D non-blocking area trigger (never -colonly)
    godot_name = get_engine_interaction_name(asset, role, name, "GODOT")
    assert godot_name == "MasterBattery_BUTTON-areacol"
    assert "-colonly" not in godot_name

    # Unity trigger volume
    unity_name = get_engine_interaction_name(asset, role, name, "UNITY")
    assert unity_name == "TRIGGER_BUTTON_MasterBattery"


# =============================================================================
# VOLUME CREATION & OUTLINER ROUTING TESTS
# =============================================================================


class MockCollection:
    def __init__(self, name: str):
        self.name = name
        self.objects = MagicMock()
        self.linked_objs: list[any] = []
        self.objects.link.side_effect = self.linked_objs.append


class MockObject:
    def __init__(self, name: str, data: any = None):
        self.name = name
        self.data = data
        self.custom_props: dict[str, any] = {}
        self.display_type = "TEXTURED"
        self.show_wire = False
        self.location = (0.0, 0.0, 0.0)
        self.rotation_euler = (0.0, 0.0, 0.0)
        self.parent = None
        self.matrix_world = MagicMock()
        self.matrix_parent_inverse = MagicMock()

    def __setitem__(self, key: str, value: any):
        self.custom_props[key] = value

    def __getitem__(self, key: str):
        return self.custom_props[key]

    def get(self, key: str, default: any = None):
        return self.custom_props.get(key, default)


def test_create_interaction_volume_box(monkeypatch):
    """Verify Box interaction volume creation, metadata tags, and collection linkage."""
    mock_mesh = MagicMock()
    mock_mesh.materials = []

    mock_bpy = MagicMock()
    mock_bpy.data.meshes.new.return_value = mock_mesh
    mock_bpy.data.objects.new.side_effect = lambda name, data: MockObject(name, data)
    monkeypatch.setattr(iv, "bpy", mock_bpy)

    target_coll = MockCollection("Cessna_Interactions")
    monkeypatch.setattr(
        iv,
        "get_or_create_engine_import_collection",
        lambda ctx, asset, role: target_coll,
    )
    monkeypatch.setattr(
        iv,
        "create_or_update_material_preset",
        lambda **kwargs: MagicMock(name="InvisMat"),
    )

    ctx = MagicMock()
    vol = create_interaction_volume(
        context=ctx,
        asset_name="Cessna",
        name="ParkingBrake",
        shape="BOX",
        role="LEVER",
        size=(0.05, 0.12, 0.05),
    )

    assert vol is not None
    assert vol.name == "Cessna_LEVER_ParkingBrake"
    assert vol.display_type == "WIRE"
    assert vol.show_wire is True

    # Multi-engine metadata invariants
    assert vol["_omnimesh_role"] == "INTERACTION_VOLUME"
    assert vol["_omnimesh_interaction_role"] == "LEVER"
    assert vol["_omnimesh_interaction_shape"] == "BOX"
    assert vol["_is_trigger"] is True
    assert vol["msfs_interaction_name"] == "Collision_LEVER_ParkingBrake"
    assert vol["ue5_trigger_name"] == "INTERACT_LEVER_ParkingBrake"
    assert vol["godot_trigger_name"] == "ParkingBrake_LEVER-areacol"
    assert vol["unity_is_trigger"] is True

    # Linked into Cessna_Interactions collection
    assert vol in target_coll.linked_objs


def test_create_interaction_volume_parenting(monkeypatch):
    """Verify interaction volume parents to the active control object."""
    mock_mesh = MagicMock()
    mock_mesh.materials = []

    mock_bpy = MagicMock()
    mock_bpy.data.meshes.new.return_value = mock_mesh
    mock_bpy.data.objects.new.side_effect = lambda name, data: MockObject(name, data)
    monkeypatch.setattr(iv, "bpy", mock_bpy)

    monkeypatch.setattr(
        iv,
        "get_or_create_engine_import_collection",
        lambda ctx, asset, role: MockCollection("Airbus_Interactions"),
    )
    monkeypatch.setattr(
        iv,
        "create_or_update_material_preset",
        lambda **kwargs: None,
    )

    parent_mesh = MockObject("Cockpit_Throttle_Lever")
    parent_mesh.type = "MESH"
    parent_mesh.location = (0.2, 1.5, 0.8)

    ctx = MagicMock()
    vol = create_interaction_volume(
        context=ctx,
        asset_name="Airbus",
        name="Throttle",
        shape="CYLINDER",
        role="LEVER",
        parent_obj=parent_mesh,
    )

    assert vol is not None
    assert vol.parent == parent_mesh
    assert vol.location == (0.2, 1.5, 0.8)
