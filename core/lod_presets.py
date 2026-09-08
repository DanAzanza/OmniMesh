"""
OmniMesh LOD Presets Subsystem.
Manages decoupled JSON-based LOD tier configuration templates, schema validation,
atomic disk I/O, and cross-session pipeline state persistence.
"""

from __future__ import annotations

import json
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

DEFAULT_LOD_PRESET_ID = "unreal_engine_5"


class LODPresetManager(BasePresetManager):
    """Manages LOD tier configuration presets (screen coverage %, target tri budgets, engine conventions)."""

    CATEGORY: ClassVar[str] = "lods"
    SCHEMA_TYPE: ClassVar[str] = "omnimesh_lod_preset"
    DEFAULT_PRESET_ID: ClassVar[str] = DEFAULT_LOD_PRESET_ID

    @classmethod
    def get_builtin_dir(cls) -> Path:
        """Returns path to shipped factory presets for LOD tier configurations."""
        return Path(__file__).resolve().parent.parent / "presets" / "lod_presets"

    @classmethod
    def get_user_dir(cls) -> Path:
        """Returns path to user custom presets directory for LOD tier configurations."""
        if bpy and hasattr(bpy.utils, "user_resource"):
            try:
                base = Path(bpy.utils.user_resource("SCRIPTS")) / "omnimesh_presets" / "lod_presets"
            except Exception:
                base = Path.home() / ".omnimesh" / "presets" / "lod_presets"
        else:
            base = Path.home() / ".omnimesh" / "presets" / "lod_presets"

        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("Could not create user LOD preset directory '%s': %s", base, exc)
        return base

    @classmethod
    def validate_preset_schema(cls, data: Any) -> Optional[dict[str, Any]]:
        """Validates LOD preset dictionary structure against schema rules."""
        if not isinstance(data, dict):
            return None

        name = str(data.get("name", "")).strip()
        if not name:
            return None

        raw_tiers = data.get("tiers", [])
        if not isinstance(raw_tiers, list) or len(raw_tiers) == 0:
            return None

        budget_mode = str(data.get("budget_mode", "PERCENTAGE")).strip().upper()
        if budget_mode not in {"PERCENTAGE", "ABSOLUTE"}:
            budget_mode = "PERCENTAGE"

        valid_tiers: list[dict[str, Any]] = []
        for idx, t in enumerate(raw_tiers):
            if not isinstance(t, dict):
                continue
            tier_name = str(t.get("name", f"LOD{idx}")).strip() or f"LOD{idx}"
            try:
                screen_pct = float(t.get("screen_size_pct", 100.0 if idx == 0 else 50.0))
                tris_pct = float(t.get("target_tris_pct", 100.0 if idx == 0 else 50.0))
            except (ValueError, TypeError):
                continue

            screen_pct = max(0.01, min(100.0, screen_pct))
            tris_pct = max(0.001, min(100.0, tris_pct))

            tier_dict: dict[str, Any] = {
                "name": tier_name,
                "screen_size_pct": round(screen_pct, 2),
                "target_tris_pct": round(tris_pct, 4),
            }

            if "target_tris" in t or budget_mode == "ABSOLUTE":
                try:
                    target_tris = max(1, int(t.get("target_tris", 1000)))
                    tier_dict["target_tris"] = target_tris
                except (ValueError, TypeError):
                    pass

            valid_tiers.append(tier_dict)

        if not valid_tiers:
            return None

        # Sort tiers descending by screen_size_pct to ensure strictly monotonic curve
        valid_tiers.sort(key=lambda item: float(item["screen_size_pct"]), reverse=True)

        # Validate optional chunking dictionary
        raw_chunk = data.get("chunking")
        chunk_dict = raw_chunk if isinstance(raw_chunk, dict) else {}
        validated_chunk = {
            "enabled": bool(chunk_dict.get("enabled", False)),
            "cell_size": max(1.0, float(chunk_dict.get("cell_size", 32.0))),
            "split_z": bool(chunk_dict.get("split_z", False)),
            "cell_size_z": max(1.0, float(chunk_dict.get("cell_size_z", 32.0))),
            "partitioning_mode": (
                chunk_dict.get("partitioning_mode", "UNIFORM_GRID")
                if chunk_dict.get("partitioning_mode") in {"UNIFORM_GRID", "ADAPTIVE_CLUSTERING"}
                else "UNIFORM_GRID"
            ),
            "adaptive_target_polys": max(1000, int(chunk_dict.get("adaptive_target_polys", 50000))),
            "enable_hlod": bool(chunk_dict.get("enable_hlod", True)),
            "hlod_start_tier": max(1, min(6, int(chunk_dict.get("hlod_start_tier", 2)))),
        }

        # Validate optional impostor block
        raw_imp = data.get("impostor")
        imp_dict = raw_imp if isinstance(raw_imp, dict) else {}
        validated_imp = {
            "enabled": bool(imp_dict.get("enabled", False)),
            "mode": str(imp_dict.get("mode", "CROSS_QUADS"))
            if imp_dict.get("mode") in {"CROSS_QUADS", "STAR_QUADS", "OCTAHEDRAL_HEMI", "OCTAHEDRAL_SPHERE"}
            else "CROSS_QUADS",
            "resolution": str(imp_dict.get("resolution", "2048"))
            if str(imp_dict.get("resolution")) in {"512", "1024", "2048", "4096"}
            else "2048",
            "replace_last_lod": bool(imp_dict.get("replace_last_lod", True)),
            "screen_size_pct": max(0.01, min(50.0, float(imp_dict.get("screen_size_pct", 1.5)))),
        }

        # Validate optional culling block
        raw_cull = data.get("culling")
        cull_dict = raw_cull if isinstance(raw_cull, dict) else {}
        validated_cull = {
            "occlusion_enabled": bool(cull_dict.get("occlusion_enabled", True)),
            "occlusion_lod_start": max(1, min(6, int(cull_dict.get("occlusion_lod_start", 1)))),
            "occlusion_ray_density": max(4, min(64, int(cull_dict.get("occlusion_ray_density", 16)))),
            "occlusion_evaluate_alpha": bool(cull_dict.get("occlusion_evaluate_alpha", True)),
            "slender_enabled": bool(cull_dict.get("slender_enabled", True)),
        }

        # Validate optional seam pinning block
        raw_pin = data.get("pinning")
        pin_dict = raw_pin if isinstance(raw_pin, dict) else {}
        validated_pin = {
            "pin_uv_seams": bool(pin_dict.get("pin_uv_seams", True)),
            "pin_material_borders": bool(pin_dict.get("pin_material_borders", True)),
        }

        validated = dict(data)
        validated["name"] = name
        validated["budget_mode"] = budget_mode
        validated["tiers"] = valid_tiers
        validated["chunking"] = validated_chunk
        validated["impostor"] = validated_imp
        validated["culling"] = validated_cull
        validated["pinning"] = validated_pin
        validated["schema_type"] = cls.SCHEMA_TYPE
        validated["version"] = int(data.get("version", 2))
        validated["target_engine"] = str(data.get("target_engine", "UE5"))
        validated["description"] = str(data.get("description", ""))
        validated["tau_sse"] = max(0.05, min(10.0, float(data.get("tau_sse", 0.8))))
        return validated

    @classmethod
    def load_presets(cls, force_reload: bool = False) -> dict[str, dict[str, Any]]:
        """Loads presets allowing user presets to override or extend shipped factory presets."""
        import sys

        with cls._get_category_lock():
            cache = cls._get_category_cache()
            init_key = f"_init_{cls.CATEGORY}"
            if getattr(sys, init_key, False) and not force_reload:
                return cache

            loaded: dict[str, dict[str, Any]] = {}

            # 1. Shipped factory presets
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
                    except Exception as exc:
                        logger.warning("Failed loading built-in LOD preset '%s': %s", p, exc)

            # 2. User custom presets (can override built-in defaults or declare new templates)
            u_dir = cls.get_user_dir()
            if u_dir.is_dir():
                for p in sorted(u_dir.glob("*.json")):
                    pid = p.stem.lower()
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            raw = json.load(f)
                        val = cls.validate_preset_schema(raw)
                        if val:
                            val["_is_builtin"] = False
                            val["_filepath"] = str(p)
                            loaded[pid] = val
                    except Exception as exc:
                        logger.warning("Failed loading user LOD preset '%s': %s", p, exc)

            cache.clear()
            cache.update(loaded)
            setattr(sys, init_key, True)
            return cache

    @classmethod
    def save_custom_preset(cls, preset_data: dict[str, Any], custom_id: Optional[str] = None) -> str:
        """Atomically saves a preset to user directory without factory write protection."""
        import os
        import tempfile
        import time

        validated = cls.validate_preset_schema(preset_data)
        if not validated:
            raise ValueError("Invalid preset schema.")

        pid = cls.sanitize_id(custom_id or validated["name"])
        target_dir = cls.get_user_dir()
        target_path = target_dir / f"{pid}.json"

        fd, tmp_path = tempfile.mkstemp(dir=str(target_dir), prefix="om_lod_", suffix=".tmp")
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
    def is_user_preset(cls, preset_id: str) -> bool:
        """Returns True if a preset file exists in the user directory (custom or user override)."""
        target_path = cls.get_user_dir() / f"{preset_id}.json"
        return target_path.is_file()

    @classmethod
    def delete_custom_preset(cls, preset_id: str) -> bool:
        """Deletes a custom user preset or resets an overridden built-in preset to factory default."""
        target_path = cls.get_user_dir() / f"{preset_id}.json"
        if not target_path.is_file():
            return False
        try:
            target_path.unlink()
            cls.load_presets(force_reload=True)
            return True
        except OSError as exc:
            logger.error("Failed deleting LOD preset '%s': %s", target_path, exc)
            return False

    @classmethod
    def get_last_active_preset(cls, preset_type: str = "") -> str:
        """Retrieves last selected LOD preset ID from persistent state."""
        state = cls.get_pipeline_state()
        presets = cls.load_presets()
        saved = str(state.get("last_lod_preset", "")).strip()
        if saved and saved in presets:
            return saved
        return cls.DEFAULT_PRESET_ID

    @classmethod
    def set_last_active_preset(cls, target_or_id: str, preset_id: Optional[str] = None) -> None:
        """Persists active LOD preset selection across sessions."""
        pid = preset_id if preset_id is not None else target_or_id
        if not pid:
            return
        cls.set_pipeline_setting("last_lod_preset", pid)
