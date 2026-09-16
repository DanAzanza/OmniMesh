"""
OmniMesh Config Presets Subsystem.
Manages JSON templates for generating MSFS configuration objects
(spatial markers, lights, cameras, exits, engines) from scratch for active assets.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, ClassVar, Optional

try:
    import bpy
except ImportError:
    bpy = None

try:
    from .pbr_presets import BasePresetManager
except (ImportError, ValueError):
    from core.pbr_presets import BasePresetManager

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PRESET_ID = "plane_general_aviation"


class ConfigPresetManager(BasePresetManager):
    """Manages Config Presets (GA Plane, Airliner, Taildragger, Airport, etc.)."""

    CATEGORY: ClassVar[str] = "config"
    SCHEMA_TYPE: ClassVar[str] = "omnimesh_config_preset"
    DEFAULT_PRESET_ID: ClassVar[str] = DEFAULT_CONFIG_PRESET_ID

    @classmethod
    def get_builtin_dir(cls) -> Path:
        """Returns path to shipped factory presets for config objects."""
        return Path(__file__).resolve().parent.parent / "presets" / "config"

    @classmethod
    def get_user_dir(cls) -> Path:
        """Returns path to user custom presets directory for config objects."""
        if bpy and hasattr(bpy.utils, "user_resource"):
            try:
                base = Path(bpy.utils.user_resource("SCRIPTS")) / "omnimesh_presets" / "config"
            except (RuntimeError, ValueError, AttributeError, TypeError):
                base = Path.home() / ".omnimesh" / "presets" / "config"
        else:
            base = Path.home() / ".omnimesh" / "presets" / "config"

        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("Could not create user config preset directory '%s': %s", base, exc)
        return base

    @classmethod
    def validate_preset_schema(cls, data: Any) -> Optional[dict[str, Any]]:
        """Validates config preset dictionary structure against schema rules."""
        if not isinstance(data, dict):
            return None

        name = str(data.get("name", "")).strip()
        if not name:
            return None

        archetype = str(data.get("archetype", "general_aviation")).strip().lower()
        validated: dict[str, Any] = {
            "$schema": cls.SCHEMA_TYPE,
            "name": name,
            "archetype": archetype,
            "description": str(data.get("description", "")).strip(),
            "is_scenery": bool(data.get("is_scenery", False)),
            "spatial": list(data.get("spatial", [])),
            "lights": list(data.get("lights", [])),
            "cameras": list(data.get("cameras", [])),
            "exits": list(data.get("exits", [])),
            "engines": list(data.get("engines", [])),
            "station_loads": list(data.get("station_loads", [])),
            "interactions": list(data.get("interactions", [])),
        }
        return validated

    @classmethod
    def get_preset(cls, preset_id: str) -> dict[str, Any]:
        """Retrieves preset by ID with safe fallback and preset_id injected."""
        presets = cls.load_presets()
        target_id = preset_id
        if target_id not in presets:
            target_id = cls.DEFAULT_PRESET_ID
        if target_id not in presets and presets:
            target_id = next(iter(presets.keys()))

        preset = dict(presets.get(target_id, {}))
        preset["preset_id"] = target_id
        return preset

    @classmethod
    def delete_preset(cls, preset_id: str) -> bool:
        """Alias to delete_custom_preset for uniform preset manager semantics."""
        return cls.delete_custom_preset(preset_id)


def get_config_preset(preset_id: str) -> dict[str, Any]:
    """Retrieves a configuration preset by ID with fallback to factory default."""
    return ConfigPresetManager.get_preset(preset_id)


def save_config_preset(preset_data: dict[str, Any], custom_id: Optional[str] = None) -> str:
    """Saves custom configuration preset to user presets directory."""
    return ConfigPresetManager.save_custom_preset(preset_data, custom_id=custom_id)


def duplicate_config_preset(source_id: str, new_name: Optional[str] = None) -> str:
    """Duplicates a configuration preset into a user custom preset."""
    return ConfigPresetManager.duplicate_preset(source_id, new_name=new_name)


def delete_config_preset(preset_id: str) -> bool:
    """Deletes a custom configuration preset."""
    return ConfigPresetManager.delete_custom_preset(preset_id)


def list_config_presets() -> list[dict[str, Any]]:
    """Lists all available (built-in and custom) configuration presets."""
    presets = ConfigPresetManager.load_presets(force_reload=True)
    items: list[dict[str, Any]] = []
    for pid, pdata in presets.items():
        entry = dict(pdata)
        entry["preset_id"] = pid
        items.append(entry)
    return items
