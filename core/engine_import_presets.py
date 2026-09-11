"""
OmniMesh Engine Import Presets Subsystem.
Manages decoupled JSON-based templates for importing full game/simulation engine projects
(MSFS 2024/2020, glTF LOD hierarchies, spatial markers, lighting, and cameras).
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

DEFAULT_ENGINE_IMPORT_PRESET_ID = "msfs_2024_aircraft"


class EngineImportPresetManager(BasePresetManager):
    """Manages Engine / Project Importer presets (MSFS 2024, MSFS 2020, etc.)."""

    CATEGORY: ClassVar[str] = "engine_import"
    SCHEMA_TYPE: ClassVar[str] = "omnimesh_engine_import_preset"
    DEFAULT_PRESET_ID: ClassVar[str] = DEFAULT_ENGINE_IMPORT_PRESET_ID

    @classmethod
    def get_builtin_dir(cls) -> Path:
        """Returns path to shipped factory presets for engine project imports."""
        return Path(__file__).resolve().parent.parent / "presets" / "engine_import"

    @classmethod
    def get_user_dir(cls) -> Path:
        """Returns path to user custom presets directory for engine imports."""
        if bpy and hasattr(bpy.utils, "user_resource"):
            try:
                base = Path(bpy.utils.user_resource("SCRIPTS")) / "omnimesh_presets" / "engine_import"
            except Exception:
                base = Path.home() / ".omnimesh" / "presets" / "engine_import"
        else:
            base = Path.home() / ".omnimesh" / "presets" / "engine_import"

        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("Could not create user engine import preset directory '%s': %s", base, exc)
        return base

    @classmethod
    def validate_preset_schema(cls, data: Any) -> Optional[dict[str, Any]]:
        """Validates engine import preset dictionary structure against schema rules."""
        if not isinstance(data, dict):
            return None

        name = str(data.get("name", "")).strip()
        if not name:
            return None

        engine = str(data.get("engine", "MSFS_2024")).strip().upper()
        if engine not in {"MSFS_2024", "MSFS_2020", "GENERIC"}:
            engine = "MSFS_2024"

        model_target = str(data.get("model_target", "EXTERIOR_ONLY")).strip().upper()
        if model_target not in {"EXTERIOR_ONLY", "INTERIOR_ONLY", "BOTH_SEPARATE"}:
            model_target = "EXTERIOR_ONLY"

        validated: dict[str, Any] = {
            "$schema": cls.SCHEMA_TYPE,
            "name": name,
            "engine": engine,
            "import_geometry": bool(data.get("import_geometry", True)),
            "import_spatial": bool(data.get("import_spatial", True)),
            "import_lights": bool(data.get("import_lights", True)),
            "import_cameras": bool(data.get("import_cameras", True)),
            "model_target": model_target,
            "use_lod0_suffix": bool(data.get("use_lod0_suffix", True)),
            "auto_assign_screen_pct": bool(data.get("auto_assign_screen_pct", True)),
            "deduplicate_materials": bool(data.get("deduplicate_materials", True)),
            "reuse_master_rig": bool(data.get("reuse_master_rig", True)),
        }

        desc = str(data.get("description", "")).strip()
        if desc:
            validated["description"] = desc

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
        data = dict(presets.get(target_id, {"name": "Fallback Preset"}))
        data["preset_id"] = target_id
        return data


def get_engine_import_preset(preset_id: str) -> dict[str, Any]:
    """Retrieves an engine import preset by ID with fallback to factory default."""
    return EngineImportPresetManager.get_preset(preset_id)


def save_engine_import_preset(preset_data: dict[str, Any], custom_id: Optional[str] = None) -> str:
    """Saves custom engine import preset to user presets directory."""
    return EngineImportPresetManager.save_custom_preset(preset_data, custom_id=custom_id)


def duplicate_engine_import_preset(source_id: str, new_name: Optional[str] = None) -> str:
    """Duplicates an engine import preset into a user custom preset."""
    return EngineImportPresetManager.duplicate_preset(source_id, new_name=new_name)


def delete_engine_import_preset(preset_id: str) -> bool:
    """Deletes a custom engine import preset."""
    return EngineImportPresetManager.delete_custom_preset(preset_id)


def list_engine_import_presets() -> list[dict[str, Any]]:
    """Lists all available (built-in and custom) engine import presets."""
    presets = EngineImportPresetManager.load_presets(force_reload=True)
    items: list[dict[str, Any]] = []
    for pid, pdata in presets.items():
        entry = dict(pdata)
        entry["preset_id"] = pid
        items.append(entry)
    return items
