"""
OmniMesh Multi-Engine Interaction Volumes & Clickspot Properties.
Kept in a dedicated submodule to strictly enforce AGENTS.md < 800 LOC limit on settings.py.
"""

from __future__ import annotations

from typing import Any

try:
    import bpy
    from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
    from bpy.types import PropertyGroup
except ImportError:
    bpy = None
    PropertyGroup = object

    def _mock_prop(**kwargs: Any) -> Any:
        return None

    BoolProperty = EnumProperty = FloatProperty = StringProperty = _mock_prop


SHAPE_ITEMS = [
    ("BOX", "Box", "Bounding box volume for switches, buttons, and rectangular triggers", "MESH_CUBE", 0),
    ("SPHERE", "Sphere", "Radial bounding sphere for omnidirectional buttons and knobs", "MESH_UVSPHERE", 1),
    ("CYLINDER", "Cylinder", "Cylindrical bounding volume for levers, dials, and wheels", "MESH_CYLINDER", 2),
]

ROLE_ITEMS = [
    ("BUTTON", "Button / Switch", "Interactive push-button or toggle switch clickspot", "RESTRICT_SELECT_OFF", 0),
    ("LEVER", "Lever / Throttle", "Linear or rotational lever / control yoke clickspot", "CON_ROTLIMIT", 1),
    ("DOOR_HANDLE", "Door / Latch", "Interactive door handle or canopy latch", "MOD_EDGESPLIT", 2),
    ("TRIGGER_ZONE", "Trigger Zone", "Non-blocking proximity / overlap interaction trigger", "SNAP_VOLUME", 3),
    ("SOCKET_ATTACH", "Socket / Attachment", "Hardware mount point or equipment attachment socket", "EMPTY_AXIS", 4),
]


class OMNIMESH_InteractionSettings(PropertyGroup):
    """Configuration options for creating non-blocking interaction volumes and clickspots."""

    shape: EnumProperty(
        name="Shape",
        items=SHAPE_ITEMS,
        default="BOX",
        description="Geometric shape of the interaction bounding volume",
    )
    role: EnumProperty(
        name="Role",
        items=ROLE_ITEMS,
        default="BUTTON",
        description="Semantic interaction role across game engines",
    )
    volume_name: StringProperty(
        name="Name",
        default="Clickspot",
        description="Descriptive identifier for the interaction volume",
    )
    size_x: FloatProperty(
        name="Size X",
        default=0.08,
        min=0.005,
        max=50.0,
        unit="LENGTH",
        description="Width / X extent of the volume in meters",
    )
    size_y: FloatProperty(
        name="Size Y",
        default=0.08,
        min=0.005,
        max=50.0,
        unit="LENGTH",
        description="Depth / Y extent of the volume in meters",
    )
    size_z: FloatProperty(
        name="Size Z",
        default=0.08,
        min=0.005,
        max=50.0,
        unit="LENGTH",
        description="Height / Z extent of the volume in meters",
    )
    parent_to_active: BoolProperty(
        name="Parent to Active",
        default=True,
        description="Parent the interaction volume to the active object so it tracks kinematics and animations",
    )
