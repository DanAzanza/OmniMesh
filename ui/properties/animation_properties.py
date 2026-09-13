"""
OmniMesh Multi-Engine Animation & Action Tagging Properties.
Kept in a dedicated submodule to strictly enforce AGENTS.md < 800 LOC limit on settings.py.
"""

from __future__ import annotations

from typing import Any

try:
    import bpy
    from bpy.props import BoolProperty, EnumProperty, StringProperty
    from bpy.types import PropertyGroup
except ImportError:
    bpy = None
    PropertyGroup = object

    def _mock_prop(**kwargs: Any) -> Any:
        return None

    BoolProperty = EnumProperty = StringProperty = _mock_prop


ANIMATION_CATEGORY_ITEMS = [
    ("GENERIC", "Generic", "Standard character, mechanical, or prop animation", "ACTION", 0),
    ("LANDING_GEAR", "Landing Gear", "Gear extension, retraction, or suspension compression", "MOD_INSTANCE", 1),
    ("FLIGHT_CONTROL", "Flight Control", "Aileron, elevator, rudder, flap, or spoiler deflection", "DRIVER", 2),
    ("DOOR", "Door / Canopy", "Passenger door, cargo ramp, or canopy open/close animation", "FILE_PARENT", 3),
    ("COCKPIT_CONTROL", "Cockpit Control", "Throttle, stick, switch, or yoke cockpit animation", "CON_ROTLIMIT", 4),
    ("PROP_BLUR", "Propeller / Rotor", "Spinning propeller, rotor disc, or turbine rotation", "TIME", 5),
]


class OMNIMESH_AnimationSettings(PropertyGroup):
    """Configuration options for tagging, baking, and exporting multi-engine animation clips."""

    semantic_category: EnumProperty(
        name="Category",
        items=ANIMATION_CATEGORY_ITEMS,
        default="GENERIC",
        description="Semantic animation category for engine-specific linking and ModelBehavior generation",
    )
    custom_guid: StringProperty(
        name="Custom GUID",
        default="",
        description="Optional custom MSFS animation GUID (leave blank for automatic UUID generation)",
    )
    auto_generate_guid: BoolProperty(
        name="Auto-Generate GUID",
        default=True,
        description="Automatically generate deterministic GUIDs for MSFS <Animation> XML tags",
    )
    export_animations: BoolProperty(
        name="Include Animations",
        default=True,
        description="Include animation actions and NLA tracks in engine exports",
    )
    generate_xml_templates: BoolProperty(
        name="Generate XML Tags",
        default=True,
        description="Automatically inject <Animation> and <PartInfo> templates into MSFS ModelInfo.xml",
    )
