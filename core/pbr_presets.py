"""
OmniMesh PBR Presets Subsystem.
Manages decoupled JSON-based templates for Import and Export, schema validation,
atomic disk I/O, and cross-session pipeline state persistence.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
from typing import Any, ClassVar, Optional

try:
    import bpy
except ImportError:
    bpy = None

logger = logging.getLogger(__name__)

DEFAULT_PRESET_ID = "unreal_engine_5"


def get_state_file() -> Path:
    """Returns path to the user state JSON file tracking cross-session preferences."""
    return BasePresetManager.get_state_file()


def get_pipeline_state() -> dict[str, Any]:
    """Retrieves entire persistent pipeline state dictionary."""
    return BasePresetManager.get_pipeline_state()


def set_pipeline_setting(key: str, value: Any) -> None:
    """Persists a single pipeline setting to user_state.json with atomic replacement."""
    BasePresetManager.set_pipeline_setting(key, value)


_PRESET_CACHE: dict[str, dict[str, Any]] = {}
_PRESET_LOCK = threading.Lock()


class BasePresetManager:
    """Abstract base class for thread-safe JSON preset management."""

    CATEGORY: ClassVar[str] = "importer"
    SCHEMA_TYPE: ClassVar[str] = "omnimesh_pbr_import"
    DEFAULT_PRESET_ID: ClassVar[str] = "unreal_engine_5"

    DOS_DEVICE_NAMES: ClassVar[set[str]] = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }

    @classmethod
    def _get_category_cache(cls) -> dict[str, dict[str, Any]]:
        return _PRESET_CACHE.setdefault(cls.CATEGORY, {})

    @classmethod
    def _get_category_lock(cls) -> threading.Lock:
        return _PRESET_LOCK

    @classmethod
    def get_state_file(cls) -> Path:
        """Returns path to the user state JSON file tracking cross-session preferences."""
        if bpy and hasattr(bpy.utils, "user_resource"):
            try:
                base = Path(bpy.utils.user_resource("SCRIPTS")) / "omnimesh_presets"
            except Exception:
                base = Path.home() / ".omnimesh" / "presets"
        else:
            base = Path.home() / ".omnimesh" / "presets"
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return base / "user_state.json"

    @classmethod
    def get_pipeline_state(cls) -> dict[str, Any]:
        """Retrieves entire persistent pipeline state dictionary."""
        sf = cls.get_state_file()
        if sf.is_file():
            try:
                with open(sf, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.debug("Failed reading pipeline state from '%s': %s", sf, exc)
        return {}

    @classmethod
    def set_pipeline_setting(cls, key: str, value: Any) -> None:
        """Persists a single pipeline setting to user_state.json with atomic replacement."""
        with cls._get_category_lock():
            sf = cls.get_state_file()
            data = cls.get_pipeline_state()
            if data.get(key) == value:
                return

            data[key] = value
            target_dir = sf.parent
            target_dir.mkdir(parents=True, exist_ok=True)

            fd, tmp_path = tempfile.mkstemp(dir=str(target_dir), prefix="om_state_", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)

                backoff = (0.05, 0.1, 0.2, 0.4, 0.8)
                for attempt, delay in enumerate(backoff):
                    try:
                        os.replace(tmp_path, sf)
                        break
                    except OSError:
                        if attempt == len(backoff) - 1:
                            raise
                        time.sleep(delay)
            except Exception as exc:
                logger.debug("Failed saving pipeline setting '%s' to '%s': %s", key, sf, exc)
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

    @classmethod
    def get_builtin_dir(cls) -> Path:
        """Returns path to shipped factory presets for this category."""
        sub = f"pbr_{cls.CATEGORY}"
        return Path(__file__).resolve().parent.parent / "presets" / sub

    @classmethod
    def get_user_dir(cls) -> Path:
        """Returns path to user custom presets directory for this category."""
        if bpy and hasattr(bpy.utils, "user_resource"):
            try:
                base = Path(bpy.utils.user_resource("SCRIPTS")) / "omnimesh_presets" / cls.CATEGORY
            except Exception:
                base = Path.home() / ".omnimesh" / "presets" / cls.CATEGORY
        else:
            base = Path.home() / ".omnimesh" / "presets" / cls.CATEGORY

        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("Could not create user preset directory '%s': %s", base, exc)
        return base

    @classmethod
    def sanitize_id(cls, name: str) -> str:
        """Sanitizes user input into a filesystem-safe identifier with DOS device name protection."""
        clean = re.sub(r"[^\w\-]", "_", name.strip().lower())
        clean = re.sub(r"_+", "_", clean).strip("_") or "custom_preset"
        if clean.upper() in cls.DOS_DEVICE_NAMES:
            clean = f"{clean}_preset"
        return clean

    @classmethod
    def validate_preset_schema(cls, data: Any) -> Optional[dict[str, Any]]:
        """Validates preset dictionary structure against schema rules."""
        if not isinstance(data, dict):
            return None

        name = str(data.get("name", "")).strip()
        if not name:
            return None

        raw_maps = data.get("maps", [])
        if not isinstance(raw_maps, list) or len(raw_maps) == 0:
            return None

        valid_maps: list[dict[str, Any]] = []
        for m in raw_maps:
            if not isinstance(m, dict):
                continue
            map_id = str(m.get("id", "")).strip()
            channels = m.get("channels", {})
            if not map_id or not isinstance(channels, dict) or not channels:
                continue

            if "suffixes" in m:
                suffixes = m.get("suffixes")
                if not isinstance(suffixes, list) or len(suffixes) == 0:
                    continue

            valid_channels: dict[str, Any] = {}
            for ch_key, ch_def in channels.items():
                if not isinstance(ch_def, dict):
                    continue
                target = str(ch_def.get("target", "")).strip()
                if not target:
                    continue
                valid_channels[str(ch_key).lower()] = {
                    "target": target,
                    "invert": bool(ch_def.get("invert", False)),
                    "default": float(ch_def.get("default", 1.0 if "occlusion" in target.lower() else 0.0)),
                }

            if not valid_channels:
                continue

            clean_map = dict(m)
            clean_map["id"] = map_id
            clean_map["channels"] = valid_channels
            if "export" in m:
                clean_map["export"] = bool(m.get("export", True))
            if "export_suffix" in m:
                clean_map["export_suffix"] = str(m.get("export_suffix", f"_{map_id}"))
            valid_maps.append(clean_map)

        if not valid_maps:
            return None

        validated = dict(data)
        validated["name"] = name
        validated["maps"] = valid_maps
        validated["version"] = int(data.get("version", 2))
        if "strategy" in data:
            validated["strategy"] = str(data["strategy"])
        return validated

    @classmethod
    def load_presets(cls, force_reload: bool = False) -> dict[str, dict[str, Any]]:
        """Loads built-in and user presets with thread-safe caching."""
        with cls._get_category_lock():
            cache = cls._get_category_cache()
            init_key = f"_init_{cls.CATEGORY}"
            if getattr(sys, init_key, False) and not force_reload:
                return cache

            loaded: dict[str, dict[str, Any]] = {}
            builtin_ids: set[str] = set()

            # 1. Load built-in presets
            b_dir = cls.get_builtin_dir()
            if b_dir.is_dir():
                for p in sorted(b_dir.glob("*.json")):
                    pid = p.stem.lower()
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            raw = json.load(f)
                        val = cls.validate_preset_schema(raw)
                        if val:
                            val["_is_builtin"] = True
                            val["_filepath"] = str(p)
                            loaded[pid] = val
                            builtin_ids.add(pid)
                    except Exception as exc:
                        logger.warning("Failed loading built-in %s preset '%s': %s", cls.CATEGORY, p, exc)

            # 2. Load user custom presets
            u_dir = cls.get_user_dir()
            if u_dir.is_dir():
                for p in sorted(u_dir.glob("*.json")):
                    pid = p.stem.lower()
                    if pid in builtin_ids:
                        pid = f"user_{pid}"
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            raw = json.load(f)
                        val = cls.validate_preset_schema(raw)
                        if val:
                            val["_is_builtin"] = False
                            val["_filepath"] = str(p)
                            loaded[pid] = val
                    except Exception as exc:
                        logger.warning("Failed loading user %s preset '%s': %s", cls.CATEGORY, p, exc)

            cache.clear()
            cache.update(loaded)
            setattr(sys, init_key, True)
            return cache

    @classmethod
    def get_preset(cls, preset_id: str) -> dict[str, Any]:
        """Retrieves preset by ID with safe fallback to DEFAULT_PRESET_ID."""
        presets = cls.load_presets()
        if preset_id in presets:
            return presets[preset_id]
        if cls.DEFAULT_PRESET_ID in presets:
            return presets[cls.DEFAULT_PRESET_ID]
        if presets:
            return next(iter(presets.values()))
        return {"name": "Fallback Preset", "maps": []}

    @classmethod
    def is_builtin(cls, preset_id: str) -> bool:
        """Returns True if preset_id is a built-in factory preset, False otherwise."""
        if not preset_id:
            preset_id = cls.DEFAULT_PRESET_ID
        presets = cls.load_presets()
        preset = presets.get(preset_id)
        if preset is None:
            preset = presets.get(cls.DEFAULT_PRESET_ID, {})
        return bool(preset.get("_is_builtin", False))

    @classmethod
    def get_builtin_preset_ids(cls) -> set[str]:
        """Returns identifiers of shipped factory presets."""
        presets = cls.load_presets()
        return {pid for pid, data in presets.items() if data.get("_is_builtin", False)}

    @classmethod
    def get_enum_items(cls) -> list[tuple[str, str, str]]:
        """Returns items for Blender EnumProperty: [(id, name, description), ...] with clean names."""
        presets = cls.load_presets(force_reload=True)
        items: list[tuple[str, str, str]] = []
        for pid, pdata in presets.items():
            name = str(pdata.get("name", pid))
            desc = str(pdata.get("description", ""))
            items.append((pid, name, desc))
        return items or [(cls.DEFAULT_PRESET_ID, "Default Profile", "Default template")]

    @classmethod
    def get_last_active_preset(cls, preset_type: str = "") -> str:
        """Retrieves last selected preset ID from persistent state."""
        state = cls.get_pipeline_state()
        category = preset_type if preset_type else cls.CATEGORY
        if category in {"export", "exporter"}:
            cat_key = "exporter"
            presets = PBRExportPresetManager.load_presets()
        else:
            cat_key = "importer"
            presets = PBRImportPresetManager.load_presets()
        key = f"last_{cat_key}_preset"
        saved = str(state.get(key, "")).strip()
        if saved and saved in presets:
            return saved
        return cls.DEFAULT_PRESET_ID

    @classmethod
    def set_last_active_preset(cls, target_or_id: str, preset_id: Optional[str] = None) -> None:
        """Persists active preset selection across sessions."""
        if preset_id is not None:
            category = target_or_id
            pid = preset_id
        else:
            category = cls.CATEGORY
            pid = target_or_id
        if not pid:
            return
        if category in {"export", "exporter"}:
            cat_key = "exporter"
        else:
            cat_key = "importer"
        key = f"last_{cat_key}_preset"
        cls.set_pipeline_setting(key, pid)

    @classmethod
    def save_custom_preset(cls, preset_data: dict[str, Any], custom_id: Optional[str] = None) -> str:
        """Atomically saves a custom preset to disk with Windows retry loop."""
        validated = cls.validate_preset_schema(preset_data)
        if not validated:
            raise ValueError("Invalid preset schema. Ensure non-empty name, maps, and channels.")

        pid = cls.sanitize_id(custom_id or validated["name"])
        builtin_ids = cls.get_builtin_preset_ids()
        if pid in builtin_ids:
            raise PermissionError(f"Cannot overwrite built-in factory preset '{pid}'. Duplicate it instead.")

        target_dir = cls.get_user_dir()
        target_path = target_dir / f"{pid}.json"

        fd, tmp_path = tempfile.mkstemp(dir=str(target_dir), prefix="om_pre_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(validated, f, indent=2)

            backoff = (0.05, 0.1, 0.2, 0.4, 0.8)
            for attempt, delay in enumerate(backoff):
                try:
                    os.replace(tmp_path, target_path)
                    break
                except OSError:
                    if attempt == len(backoff) - 1:
                        raise
                    time.sleep(delay)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

        cls.load_presets(force_reload=True)
        return pid

    @classmethod
    def duplicate_preset(cls, source_id: str, new_name: str = "", overrides: Optional[dict[str, Any]] = None) -> str:
        """Clones an existing preset into a new unique custom preset, applying optional overrides."""
        source = cls.get_preset(source_id)
        clone = copy.deepcopy(source)

        base_name = new_name.strip() if new_name and new_name.strip() else f"{source.get('name', source_id)} (Copy)"
        clone["name"] = base_name

        if overrides:
            for k, v in overrides.items():
                clone[k] = v

        base_id = cls.sanitize_id(base_name)
        existing = cls.load_presets()
        builtin_ids = cls.get_builtin_preset_ids()

        candidate_id = base_id
        counter = 2
        while candidate_id in existing or candidate_id in builtin_ids:
            candidate_id = f"{base_id}_{counter}"
            counter += 1

        return cls.save_custom_preset(clone, custom_id=candidate_id)

    @classmethod
    def delete_custom_preset(cls, preset_id: str) -> bool:
        """Deletes a custom user preset from disk with retry loop. Refuses to delete built-ins."""
        presets = cls.load_presets()
        if preset_id not in presets:
            return False

        preset = presets[preset_id]
        if preset.get("_is_builtin", False):
            logger.warning("Cannot delete built-in %s preset '%s'", cls.CATEGORY, preset_id)
            return False

        filepath = preset.get("_filepath")
        if filepath and os.path.exists(filepath):
            for attempt in range(3):
                try:
                    os.remove(filepath)
                    cls.load_presets(force_reload=True)
                    return True
                except OSError as exc:
                    if attempt == 2:
                        logger.error("Failed deleting %s preset '%s': %s", cls.CATEGORY, filepath, exc)
                        return False
                    time.sleep(0.05)
        return False


class PBRImportPresetManager(BasePresetManager):
    """Manages PBR texture importer presets (source channel definitions, suffixes, color spaces)."""

    CATEGORY = "importer"
    SCHEMA_TYPE = "omnimesh_pbr_import"
    DEFAULT_PRESET_ID = "unreal_engine_5"


class PBRExportPresetManager(BasePresetManager):
    """Manages unified engine export presets (target engine, packaging strategy, bit depth, naming)."""

    CATEGORY = "exporter"
    SCHEMA_TYPE = "omnimesh_pbr_export"
    DEFAULT_PRESET_ID = "unreal_engine_5"


# Backward compatibility alias
PBRImporterPresetManager = PBRImportPresetManager
