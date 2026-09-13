"""
OmniMesh Config Preset Properties.
Kept in a dedicated submodule to strictly enforce AGENTS.md < 800 LOC limit on settings.py.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

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

try:
    from ...core.config_presets import ConfigPresetManager, DEFAULT_CONFIG_PRESET_ID
except (ImportError, ValueError):
    from core.config_presets import ConfigPresetManager, DEFAULT_CONFIG_PRESET_ID


def get_config_preset_items(self: Any, context: Any) -> list[tuple[str, str, str]]:
    """Dynamic EnumProperty callback listing available config presets."""
    presets = ConfigPresetManager.load_presets()
    items = []
    for pid, pdata in sorted(presets.items()):
        name = str(pdata.get("name", pid))
        desc = str(pdata.get("description", f"Preset {pid}"))
        items.append((pid, name, desc))

    if not items:
        items.append((DEFAULT_CONFIG_PRESET_ID, "General Aviation", "Default GA preset"))
    return items


def on_config_preset_updated(self: Any, context: Any) -> None:
    """Invoked when user switches active config preset."""
    pass


class OMNIMESH_ConfigPresetSettings(PropertyGroup):
    """Configuration options for spawning preset config objects into the scene."""

    config_preset: EnumProperty(
        name="Config Preset",
        items=get_config_preset_items,
        description="Active configuration preset to spawn",
        update=on_config_preset_updated,
    )
    include_spatial: BoolProperty(
        name="Spatial & Contact Points",
        default=True,
        description="Include Datum, CG, landing gear wheels, scrape points, and fuel tanks",
    )
    include_lights: BoolProperty(
        name="Aircraft Lights",
        default=True,
        description="Include navigation, strobe, beacon, landing, and taxi lights",
    )
    include_cameras: BoolProperty(
        name="Cockpit & External Cameras",
        default=True,
        description="Include pilot eyepoint, cockpit camera, and external quickviews",
    )
    include_exits: BoolProperty(
        name="Exits & Doors",
        default=True,
        description="Include passenger doors, cargo doors, and jetway attach points",
    )
    include_engines: BoolProperty(
        name="Engines & Thrust Vectors",
        default=True,
        description="Include engine and propeller reference coordinates",
    )
    last_spawn_summary: StringProperty(
        name="Last Spawn Summary",
        default="",
    )


def register():
    if bpy and hasattr(bpy.utils, "register_class"):
        try:
            bpy.utils.register_class(OMNIMESH_ConfigPresetSettings)
        except Exception as exc:
            logger.debug("Register skipped OMNIMESH_ConfigPresetSettings: %s", exc)


def unregister():
    if bpy and hasattr(bpy.utils, "unregister_class"):
        try:
            bpy.utils.unregister_class(OMNIMESH_ConfigPresetSettings)
        except Exception as exc:
            logger.debug("Unregister skipped OMNIMESH_ConfigPresetSettings: %s", exc)
