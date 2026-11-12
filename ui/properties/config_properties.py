# pyright: reportInvalidTypeForm=none
"""
OmniMesh Config Preset Properties.
Kept in a dedicated submodule to strictly enforce AGENTS.md < 800 LOC limit on settings.py.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.props import BoolProperty, EnumProperty, StringProperty
    from bpy.types import PropertyGroup
else:
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

from .guards import PresetSyncGuard, StateRestorationGuard

try:
    from ...core.config_presets import DEFAULT_CONFIG_PRESET_ID, ConfigPresetManager
except (ImportError, ValueError):
    from core.config_presets import DEFAULT_CONFIG_PRESET_ID, ConfigPresetManager


def get_config_preset_items(self: Any, context: Any) -> list[tuple[str, str, str]]:
    """Dynamic EnumProperty callback listing available config presets."""
    presets = ConfigPresetManager.load_presets()
    items = []
    for pid, pdata in sorted(presets.items()):
        name = str(pdata.get("name", pid))
        items.append((pid, name, name))

    if not items:
        items.append((DEFAULT_CONFIG_PRESET_ID, "General Aviation", "General Aviation"))
    return items


def on_config_preset_updated(self: Any, context: Any) -> None:
    """Invoked when user switches active config preset; hydrates category toggles."""
    if StateRestorationGuard.is_active() or PresetSyncGuard.is_locked():
        return
    preset_id = getattr(self, "config_preset", "") or DEFAULT_CONFIG_PRESET_ID
    preset = ConfigPresetManager.get_preset(preset_id)
    with PresetSyncGuard():
        self.include_spatial = bool(preset.get("include_spatial", True))
        self.include_lights = bool(preset.get("include_lights", True))
        self.include_cameras = bool(preset.get("include_cameras", True))
        self.include_exits = bool(preset.get("include_exits", True))
        self.include_engines = bool(preset.get("include_engines", True))
        self.include_interactions = bool(preset.get("include_interactions", True))


def on_config_category_updated(self: Any, context: Any) -> None:
    """Auto-saves category toggles to active custom config preset when modified."""
    if StateRestorationGuard.is_active() or PresetSyncGuard.is_locked():
        return
    preset_id = getattr(self, "config_preset", "") or DEFAULT_CONFIG_PRESET_ID
    if ConfigPresetManager.is_builtin(preset_id):
        return
    try:
        import copy

        pdata = copy.deepcopy(ConfigPresetManager.get_preset(preset_id))
        pdata["include_spatial"] = bool(getattr(self, "include_spatial", True))
        pdata["include_lights"] = bool(getattr(self, "include_lights", True))
        pdata["include_cameras"] = bool(getattr(self, "include_cameras", True))
        pdata["include_exits"] = bool(getattr(self, "include_exits", True))
        pdata["include_engines"] = bool(getattr(self, "include_engines", True))
        pdata["include_interactions"] = bool(getattr(self, "include_interactions", True))
        ConfigPresetManager.save_custom_preset(pdata, custom_id=preset_id)
    except Exception as exc:
        logger.debug("Auto-save custom config preset skipped: %s", exc)


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
        update=on_config_category_updated,
    )
    include_lights: BoolProperty(
        name="Aircraft Lights",
        default=True,
        description="Include navigation, strobe, beacon, landing, and taxi lights",
        update=on_config_category_updated,
    )
    include_cameras: BoolProperty(
        name="Cockpit & External Cameras",
        default=True,
        description="Include pilot eyepoint, cockpit camera, and external quickviews",
        update=on_config_category_updated,
    )
    include_exits: BoolProperty(
        name="Exits & Doors",
        default=True,
        description="Include passenger doors, cargo doors, and jetway attach points",
        update=on_config_category_updated,
    )
    include_engines: BoolProperty(
        name="Engines & Thrust Vectors",
        default=True,
        description="Include engine and propeller reference coordinates",
        update=on_config_category_updated,
    )
    include_interactions: BoolProperty(
        name="Interaction & Clickspots",
        default=True,
        description="Include interaction triggers and clickspot volumes",
        update=on_config_category_updated,
    )
    last_spawn_summary: StringProperty(
        name="Last Spawn Summary",
        default="",
    )
    show_helpers: BoolProperty(
        name="Vehicle & MSFS Helpers",
        default=False,
        description="Show spatial, ground, lighting, camera, and attachment helper tools",
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
