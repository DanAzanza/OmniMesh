"""
OmniMesh Multi-Engine Material Preset Properties.
Kept in a dedicated submodule to strictly enforce AGENTS.md < 800 LOC limit on settings.py.
"""

from __future__ import annotations

from typing import Any

try:
    import bpy
    from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, StringProperty
    from bpy.types import PropertyGroup
except ImportError:
    bpy = None
    PropertyGroup = object

    def _mock_prop(**kwargs: Any) -> Any:
        return None

    BoolProperty = EnumProperty = FloatProperty = FloatVectorProperty = StringProperty = _mock_prop


MATERIAL_PRESET_ITEMS = [
    ("PBR_STANDARD", "PBR Standard", "Opaque standard metallic/roughness PBR material", "MATERIAL", 0),
    (
        "GLASS_TRANSPARENT",
        "Glass / Windshield",
        "Physical transparent glass with refraction (MSFS Windshield / UE5 Translucent / Unity)",
        "SHADING_RENDERED",
        1,
    ),
    (
        "FLOATING_DECAL",
        "Floating Decal",
        "Transparent decal with polygon offset and decimation protection",
        "MOD_UVPROJECT",
        2,
    ),
    (
        "INVISIBLE_COLLIDER",
        "Invisible / Collision",
        "Invisible trigger / collision material (MSFS Type 12 / UE5 UCX / Unity Trigger)",
        "MESH_ICOSPHERE",
        3,
    ),
    (
        "EMISSIVE_LIGHT",
        "Emissive Light",
        "Self-illuminated emissive material for cockpit instruments and lamps",
        "LIGHT_SUN",
        4,
    ),
]


class OMNIMESH_MaterialPresetSettings(PropertyGroup):
    """Properties for creating and assigning multi-engine shader presets."""

    preset_type: EnumProperty(
        name="Material Preset",
        items=MATERIAL_PRESET_ITEMS,
        default="PBR_STANDARD",
        description="Multi-engine shader preset to generate and apply",
    )
    material_name: StringProperty(
        name="Material Name",
        default="New_Material",
        description="Name of the material datablock to create or update",
    )
    base_color: FloatVectorProperty(
        name="Base Color",
        subtype="COLOR",
        size=4,
        default=(0.8, 0.8, 0.8, 1.0),
        min=0.0,
        max=1.0,
        description="Base diffuse/albedo color and alpha",
    )
    roughness: FloatProperty(
        name="Roughness",
        default=0.4,
        min=0.0,
        max=1.0,
        description="Surface roughness (0.0 = mirror, 1.0 = diffuse matte)",
    )
    metallic: FloatProperty(
        name="Metallic",
        default=0.0,
        min=0.0,
        max=1.0,
        description="Metallic reflectance (0.0 = dielectric, 1.0 = metal)",
    )
    emission_strength: FloatProperty(
        name="Emission Strength",
        default=5.0,
        min=0.0,
        max=100.0,
        description="Luminous emission intensity for emissive materials",
    )
    apply_to_selected: BoolProperty(
        name="Assign to Selected",
        default=True,
        description="Assign the created material preset to all currently selected mesh objects",
    )
