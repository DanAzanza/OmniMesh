"""
OmniMesh Property Callback and Synchronization Handlers.
Contains reactive update callbacks, project directory detectors, preset hydrators, and persistent state restorers.
"""

import copy
import logging
from typing import Any

from .guards import MapSyncGuard, PresetSyncGuard, StateRestorationGuard
from .lod_properties import sync_preset_tiers_from_preset
from .pbr_properties import sync_export_maps_from_preset, sync_maps_from_preset

try:
    from ...core.engine_import_presets import (
        DEFAULT_ENGINE_IMPORT_PRESET_ID,
        EngineImportPresetManager,
    )
    from ...core.lod_presets import (
        DEFAULT_LOD_PRESET_ID,
        LODPresetManager,
    )
    from ...core.metrics import (
        compute_bounding_sphere,
        compute_distance_from_screen_size,
        compute_vertical_fov,
    )
    from ...core.pbr_presets import (
        PBRExportPresetManager,
        PBRImportPresetManager,
        get_pipeline_state,
        set_pipeline_setting,
    )
    from ..utils import (
        get_asset_base_meshes,
        get_asset_existing_lods,
        resolve_effective_asset_name,
    )
except (ImportError, ValueError):
    from core.engine_import_presets import (
        DEFAULT_ENGINE_IMPORT_PRESET_ID,
        EngineImportPresetManager,
    )
    from core.lod_presets import (
        DEFAULT_LOD_PRESET_ID,
        LODPresetManager,
    )
    from core.metrics import (
        compute_bounding_sphere,
        compute_distance_from_screen_size,
        compute_vertical_fov,
    )
    from core.pbr_presets import (
        PBRExportPresetManager,
        PBRImportPresetManager,
        get_pipeline_state,
        set_pipeline_setting,
    )
    from ui.utils import (
        get_asset_base_meshes,
        get_asset_existing_lods,
        resolve_effective_asset_name,
    )

try:
    import bpy
except ImportError:
    bpy = None

logger = logging.getLogger(__name__)

ENGINE_TO_FACTORY_PRESET: dict[str, str] = {
    "UE5": "unreal_engine_5",
    "UNITY_6": "unity_hdrp_maskmap",
    "GODOT_4": "godot_4_orm",
    "MSFS_2024": "msfs_2024_comp",
}


def update_bridge_status_cached(self: Any, context: Any) -> None:
    """Non-blocking status update hook for project directory changes."""
    if not context or not hasattr(context, "scene"):
        return
    try:
        if __package__:
            from ...bridges.manager import BridgeManager
        else:
            from bridges.manager import BridgeManager

        props = context.scene.lod_tool
        engine = props.target_engine
        proj_dir = props.engine_project_path
        if not proj_dir:
            props.bridge_status_text = "Project Path not set"
            props.bridge_connected = False
            return

        is_ready, msg = BridgeManager.ping_engine(engine, proj_dir)
        props.bridge_connected = is_ready
        props.bridge_status_text = msg if is_ready else f"Not Ready: {msg}"
    except Exception as exc:
        logger.debug("Bridge status refresh: %s", exc)


def on_target_engine_updated(self: Any, context: Any) -> None:
    """Synchronizes target engine selection with export preset and bridge status without mutating presets."""
    if hasattr(self, "export_directory"):
        try:
            try:
                from core.project_detector import detect_engine_project
            except ImportError:
                from ...core.project_detector import detect_engine_project

            engine = getattr(self, "target_engine", "UE5")
            detected = detect_engine_project(self.export_directory, engine)
            if detected and getattr(self, "engine_project_path", "") != detected:
                self.engine_project_path = detected
        except Exception as exc:
            logger.debug("Auto engine project detection skipped: %s", exc)
    update_bridge_status_cached(self, context)
    if StateRestorationGuard.is_active() or PresetSyncGuard.is_locked():
        return
    with PresetSyncGuard():
        engine = getattr(self, "target_engine", "MSFS_2024")
        export_preset_id = getattr(self, "pbr_export_preset", "")
        try:
            from core.pbr_presets import PBRExportPresetManager
        except ImportError:
            from ...core.pbr_presets import PBRExportPresetManager

        current_preset = PBRExportPresetManager.get_preset(export_preset_id) if export_preset_id else {}
        if current_preset.get("target_engine") != engine:
            factory_id = ENGINE_TO_FACTORY_PRESET.get(engine, "unreal_engine_5")
            if hasattr(self, "pbr_export_preset"):
                self.pbr_export_preset = factory_id
            if hasattr(self, "pbr_preset"):
                self.pbr_preset = factory_id

            new_preset = PBRExportPresetManager.get_preset(factory_id)
            if hasattr(self, "pbr_export_texture_strategy"):
                self.pbr_export_texture_strategy = new_preset.get("strategy", "SMART_AUTO")
            if hasattr(self, "pbr_export_bit_depth"):
                self.pbr_export_bit_depth = str(new_preset.get("bit_depth", 8))
            if hasattr(self, "pbr_export_naming_pattern"):
                self.pbr_export_naming_pattern = new_preset.get("naming_pattern", "{material}{suffix}")
            sync_export_maps_from_preset(self, new_preset)


def on_export_preset_updated(self: Any, context: Any) -> None:
    """Synchronizes active export preset with engine container and texture packing parameters."""
    if StateRestorationGuard.is_active():
        return
    export_preset_id = getattr(self, "pbr_export_preset", "")
    if not export_preset_id:
        return
    try:
        from core.pbr_presets import PBRExportPresetManager
    except ImportError:
        from ...core.pbr_presets import PBRExportPresetManager

    # Persist choice across Blender restarts
    PBRExportPresetManager.set_last_active_preset(export_preset_id)

    if PresetSyncGuard.is_locked():
        return

    with PresetSyncGuard():
        preset = PBRExportPresetManager.get_preset(export_preset_id)
        target_eng = preset.get("target_engine")
        if target_eng and hasattr(self, "target_engine"):
            self.target_engine = target_eng
            update_bridge_status_cached(self, context)
        if hasattr(self, "pbr_export_texture_strategy"):
            self.pbr_export_texture_strategy = preset.get("strategy", "SMART_AUTO")
        if hasattr(self, "pbr_export_bit_depth"):
            self.pbr_export_bit_depth = str(preset.get("bit_depth", 8))
        if hasattr(self, "pbr_export_naming_pattern"):
            self.pbr_export_naming_pattern = preset.get("naming_pattern", "{material}{suffix}")
        if hasattr(self, "pbr_preset"):
            self.pbr_preset = export_preset_id
        sync_export_maps_from_preset(self, preset)


def on_import_preset_updated(self: Any, _context: Any) -> None:
    """Persists active import preset selection across Blender restarts and synchronizes map editor."""
    if StateRestorationGuard.is_active() or PresetSyncGuard.is_locked() or MapSyncGuard.is_active():
        return
    import_preset_id = getattr(self, "pbr_import_preset", "")
    if not import_preset_id:
        return
    PBRImportPresetManager.set_last_active_preset(import_preset_id)
    preset = PBRImportPresetManager.get_preset(import_preset_id)
    sync_maps_from_preset(self, preset)


def on_legacy_preset_updated(self: Any, context: Any) -> None:
    """Syncs legacy pbr_preset assignments to pbr_export_preset."""
    if StateRestorationGuard.is_active() or PresetSyncGuard.is_locked():
        return
    legacy_id = getattr(self, "pbr_preset", "")
    if legacy_id and hasattr(self, "pbr_export_preset"):
        with PresetSyncGuard():
            self.pbr_export_preset = legacy_id


def _handle_cow_export_setting(self: Any, context: Any, override_key: str, new_value: Any) -> None:
    """Applies modified setting to custom preset or automatically duplicates factory preset via Copy-on-Write."""
    if StateRestorationGuard.is_active() or PresetSyncGuard.is_locked():
        return
    if not context or not getattr(context, "window_manager", None):
        return

    preset_id = getattr(self, "pbr_export_preset", "")
    if not preset_id:
        return

    if PBRExportPresetManager.is_builtin(preset_id):
        # Built-in factory preset -> Duplicate with override in atomic transaction
        new_id = PBRExportPresetManager.duplicate_preset(preset_id, overrides={override_key: new_value})
        with PresetSyncGuard():
            self.pbr_export_preset = new_id
            if hasattr(self, "pbr_preset"):
                self.pbr_preset = new_id
        PBRExportPresetManager.set_last_active_preset(new_id)
    else:
        # Existing user custom preset -> Persist directly to disk
        try:
            pdata = copy.deepcopy(PBRExportPresetManager.get_preset(preset_id))
            pdata[override_key] = new_value
            PBRExportPresetManager.save_custom_preset(pdata, custom_id=preset_id)
        except Exception as exc:
            logger.debug("Failed auto-saving custom preset '%s': %s", preset_id, exc)


def on_export_strategy_updated(self: Any, context: Any) -> None:
    val = getattr(self, "pbr_export_texture_strategy", "CONVERT_PNG")
    _handle_cow_export_setting(self, context, "strategy", val)


def on_export_bit_depth_updated(self: Any, context: Any) -> None:
    val = int(getattr(self, "pbr_export_bit_depth", "8"))
    _handle_cow_export_setting(self, context, "bit_depth", val)


def on_export_naming_updated(self: Any, context: Any) -> None:
    val = getattr(self, "pbr_export_naming_pattern", "{material}{suffix}")
    _handle_cow_export_setting(self, context, "naming_pattern", val)


def on_import_directory_updated(self: Any, _context: Any) -> None:
    if StateRestorationGuard.is_active():
        return
    val = getattr(self, "pbr_import_directory", "")
    try:
        set_pipeline_setting("pbr_import_directory", val)
    except Exception as exc:
        logger.debug("Persist import directory: %s", exc)


def on_import_path_mode_updated(self: Any, _context: Any) -> None:
    if StateRestorationGuard.is_active():
        return
    val = getattr(self, "pbr_import_path_mode", "RELATIVE")
    try:
        set_pipeline_setting("pbr_import_path_mode", val)
    except Exception as exc:
        logger.debug("Persist path mode: %s", exc)


def on_export_directory_updated(self: Any, context: Any) -> None:
    if StateRestorationGuard.is_active():
        return
    val = getattr(self, "export_directory", "")
    try:
        set_pipeline_setting("export_directory", val)
    except Exception as exc:
        logger.debug("Persist export directory: %s", exc)

    try:
        try:
            from core.project_detector import detect_engine_project
        except ImportError:
            from ...core.project_detector import detect_engine_project

        engine = getattr(self, "target_engine", "UE5")
        detected = detect_engine_project(val, engine)
        if detected and getattr(self, "engine_project_path", "") != detected:
            self.engine_project_path = detected
            update_bridge_status_cached(self, context)
    except Exception as exc:
        logger.debug("Project auto-detection on export dir update: %s", exc)


def on_import_ao_mode_updated(self: Any, _context: Any) -> None:
    if StateRestorationGuard.is_active():
        return
    val = getattr(self, "pbr_import_ao_mode", "MULTIPLY")
    try:
        set_pipeline_setting("pbr_import_ao_mode", val)
    except Exception as exc:
        logger.debug("Persist AO mode: %s", exc)


def on_import_preserve_updated(self: Any, _context: Any) -> None:
    if StateRestorationGuard.is_active():
        return
    val = getattr(self, "pbr_import_preserve_existing", False)
    try:
        set_pipeline_setting("pbr_import_preserve_existing", val)
    except Exception as exc:
        logger.debug("Persist preserve existing: %s", exc)


def on_engine_project_path_updated(self: Any, context: Any) -> None:
    update_bridge_status_cached(self, context)
    if StateRestorationGuard.is_active():
        return
    val = getattr(self, "engine_project_path", "")
    try:
        set_pipeline_setting("engine_project_path", val)
    except Exception as exc:
        logger.debug("Persist engine project path: %s", exc)


def on_enable_live_sync_updated(self: Any, _context: Any) -> None:
    if StateRestorationGuard.is_active():
        return
    val = getattr(self, "enable_live_sync", True)
    try:
        set_pipeline_setting("enable_live_sync", val)
    except Exception as exc:
        logger.debug("Persist enable live sync: %s", exc)


def on_batch_mode_updated(self: Any, _context: Any) -> None:
    if StateRestorationGuard.is_active():
        return
    val = getattr(self, "batch_mode", False)
    try:
        set_pipeline_setting("batch_mode", val)
    except Exception as exc:
        logger.debug("Persist batch mode: %s", exc)


def on_batch_source_updated(self: Any, _context: Any) -> None:
    if StateRestorationGuard.is_active():
        return
    val = getattr(self, "batch_source_directory", "")
    try:
        set_pipeline_setting("batch_source_directory", val)
    except Exception as exc:
        logger.debug("Persist batch source: %s", exc)


if bpy and hasattr(bpy, "app") and hasattr(bpy.app, "handlers"):

    @bpy.app.handlers.persistent
    def restore_preset_state_on_load(dummy: Any = None) -> None:
        """Restores last used preset selections and pipeline settings upon startup or file load."""
        if not bpy or not hasattr(bpy, "data"):
            return

        state = get_pipeline_state()
        last_exp = PBRExportPresetManager.get_last_active_preset()
        last_imp = PBRImportPresetManager.get_last_active_preset()
        last_lod = LODPresetManager.get_last_active_preset()

        with StateRestorationGuard(), PresetSyncGuard():
            for scene in getattr(bpy.data, "scenes", []):
                props = getattr(scene, "lod_tool", None)
                if not props or getattr(props, "is_state_restored", False):
                    continue
                props.is_state_restored = True
                exp_to_set = last_exp or "unreal_engine_5"
                imp_to_set = last_imp or "unreal_engine_5"
                lod_to_set = last_lod or "unreal_engine_5"
                if hasattr(props, "pbr_export_preset"):
                    props.pbr_export_preset = exp_to_set
                if hasattr(props, "pbr_preset"):
                    props.pbr_preset = exp_to_set
                if hasattr(props, "pbr_import_preset"):
                    props.pbr_import_preset = imp_to_set
                    preset = PBRImportPresetManager.get_preset(imp_to_set)
                    sync_maps_from_preset(props, preset)
                if hasattr(props, "lod_preset"):
                    props.lod_preset = lod_to_set
                    lod_preset_data = LODPresetManager.get_preset(lod_to_set)
                    sync_preset_tiers_from_preset(props, lod_preset_data)

                # Hydrate persistent preferences
                if "pbr_import_directory" in state and hasattr(props, "pbr_import_directory"):
                    props.pbr_import_directory = state["pbr_import_directory"]
                if "export_directory" in state and hasattr(props, "export_directory"):
                    props.export_directory = state["export_directory"]
                if "pbr_import_path_mode" in state and hasattr(props, "pbr_import_path_mode"):
                    props.pbr_import_path_mode = state["pbr_import_path_mode"]
                if "pbr_import_ao_mode" in state and hasattr(props, "pbr_import_ao_mode"):
                    props.pbr_import_ao_mode = state["pbr_import_ao_mode"]
                if "pbr_import_preserve_existing" in state and hasattr(props, "pbr_import_preserve_existing"):
                    props.pbr_import_preserve_existing = state["pbr_import_preserve_existing"]
                if "engine_project_path" in state and hasattr(props, "engine_project_path"):
                    props.engine_project_path = state["engine_project_path"]
                if "enable_live_sync" in state and hasattr(props, "enable_live_sync"):
                    props.enable_live_sync = state["enable_live_sync"]
                if "batch_mode" in state and hasattr(props, "batch_mode"):
                    props.batch_mode = state["batch_mode"]
                if "batch_source_directory" in state and hasattr(props, "batch_source_directory"):
                    props.batch_source_directory = state["batch_source_directory"]
else:
    restore_preset_state_on_load = None


def get_lod_preset_items(self: Any, context: Any) -> list[tuple[str, str, str]]:
    """Dynamic enum items for LOD Tier Configuration Presets."""
    try:
        return LODPresetManager.get_enum_items()
    except Exception:
        return [("unreal_engine_5", "Unreal Engine 5 (Standard)", "Default template")]


_ASSET_LOD_STATE_CACHE: dict[str, list[dict[str, Any]]] = {}
_LAST_ACTIVE_ASSET_NAME: str = ""


def serialize_asset_lod_state(props: Any, asset_name: str) -> None:
    """Caches customized LOD tier properties for the given asset before switching away."""
    if not props or not hasattr(props, "lods") or not asset_name or asset_name in ("AUTO", "NONE"):
        return
    tier_list = []
    for tier in props.lods:
        tier_list.append(
            {
                "name": getattr(tier, "name", "LOD"),
                "lod_index": getattr(tier, "lod_index", 0),
                "level_index": getattr(tier, "level_index", 0),
                "screen_size_pct": getattr(tier, "screen_size_pct", 50.0),
                "target_tris_pct": getattr(tier, "target_tris_pct", 50.0),
                "target_tris": getattr(tier, "target_tris", 1000),
                "triangle_target": getattr(tier, "triangle_target", 1000),
                "is_impostor": getattr(tier, "is_impostor", False),
                "last_baked_target_pct": getattr(tier, "last_baked_target_pct", -1.0),
                "last_baked_screen_pct": getattr(tier, "last_baked_screen_pct", -1.0),
                "state": getattr(tier, "state", "PLANNED"),
            }
        )
    _ASSET_LOD_STATE_CACHE[asset_name] = tier_list


def on_active_asset_updated(props: Any, context: Any) -> None:
    """Callback when user switches the active asset dropdown."""
    global _LAST_ACTIVE_ASSET_NAME
    curr = getattr(props, "export_base_name", "") or _LAST_ACTIVE_ASSET_NAME
    if curr and curr not in ("AUTO", "NONE"):
        serialize_asset_lod_state(props, curr)
    new_asset = getattr(props, "active_asset", "")
    _LAST_ACTIVE_ASSET_NAME = new_asset
    project_preset_tiers(props, context, asset_name=new_asset)


def project_preset_tiers(props: Any, context: Any = None, asset_name: str = "", ignore_cache: bool = False) -> None:
    """Projects preset LOD tiers onto props.lods based on the resolved asset and preset definition.

    Inspects current scene state:
    - Tier 0 is marked SOURCE (read-only baseline).
    - If sibling collections exist in the scene, compares targets with last baked values:
      sets BAKED if matching, or OUT_OF_SYNC if modified.
    - If collection does not exist in the scene, sets PLANNED.
    Restores cached tier state if previously tuned by user.
    """
    if not props:
        return

    ctx = context or getattr(bpy, "context", None)
    if (not asset_name or asset_name in ("AUTO", "NONE")) and ctx:
        asset_name = resolve_effective_asset_name(ctx, props)

    base_meshes = get_asset_base_meshes(ctx, asset_name) if (ctx and asset_name) else []
    existing_lods = get_asset_existing_lods(ctx, asset_name) if (ctx and asset_name) else {}

    # Calculate bounding envelope & metrics
    all_coords = []
    base_tris = 0
    total_mat_slots = 0
    for obj in base_meshes:
        if hasattr(obj, "data") and hasattr(obj.data, "polygons"):
            polys = obj.data.polygons
            if polys:
                first = polys[0]
                if hasattr(first, "vertices"):
                    base_tris += sum(max(1, len(p.vertices) - 2) for p in polys)
                else:
                    base_tris += len(polys)
        total_mat_slots += len(obj.material_slots) if hasattr(obj, "material_slots") else 0
        m_w = getattr(obj, "matrix_world", None)
        if m_w:
            bbox = getattr(obj, "bound_box", None)
            if bbox:
                try:
                    from mathutils import Vector

                    all_coords.extend([m_w @ Vector(b) for b in bbox])
                except Exception:
                    if hasattr(obj, "data") and hasattr(obj.data, "vertices"):
                        all_coords.extend([m_w @ v.co for v in obj.data.vertices])
            elif hasattr(obj, "data") and hasattr(obj.data, "vertices"):
                all_coords.extend([m_w @ v.co for v in obj.data.vertices])

    radius = 1.0
    center = (0.0, 0.0, 0.0)
    if all_coords:
        center, radius = compute_bounding_sphere(all_coords)

    cam_angle = 1.0471975511965976  # 60 deg
    sensor_fit = "AUTO"
    res_x = 1920
    res_y = 1080
    if ctx and hasattr(ctx, "scene"):
        cam = getattr(ctx.scene, "camera", None)
        if cam and getattr(cam, "type", "") == "CAMERA":
            cam_angle = getattr(getattr(cam, "data", None), "angle", cam_angle)
            sensor_fit = getattr(getattr(cam, "data", None), "sensor_fit", sensor_fit)
        render = getattr(ctx.scene, "render", None)
        if render:
            res_x = max(1, render.resolution_x)
            res_y = max(1, render.resolution_y)

    aspect_ratio = res_x / float(res_y)
    fov_v = compute_vertical_fov(cam_angle, aspect_ratio, sensor_fit)

    props.bounding_radius = radius
    props.bounding_center = center
    props.base_triangles = base_tris
    props.screen_coverage_lod0 = 100.0
    props.is_configured = True
    if asset_name and asset_name not in ("AUTO", "NONE", "Asset"):
        props.export_base_name = asset_name

    preset_id = getattr(props, "lod_preset", "") or DEFAULT_LOD_PRESET_ID
    preset_data = LODPresetManager.get_preset(preset_id)
    if ignore_cache and asset_name and asset_name in _ASSET_LOD_STATE_CACHE:
        del _ASSET_LOD_STATE_CACHE[asset_name]
    cached_tiers = None if ignore_cache else _ASSET_LOD_STATE_CACHE.get(asset_name)
    preset_tiers = cached_tiers if cached_tiers else preset_data.get("tiers", [])

    props.lods.clear()
    for i, t_def in enumerate(preset_tiers):
        item = props.lods.add()
        item.name = str(t_def.get("name", f"LOD{i}"))
        item.lod_index = i
        item.level_index = i
        s_pct = float(t_def.get("screen_size_pct", 100.0 if i == 0 else 50.0))
        item.screen_size_pct = s_pct

        t_pct = float(t_def.get("target_tris_pct", 100.0 if i == 0 else 50.0))
        item.target_tris_pct = t_pct
        item.target_tris = (
            max(6, int(base_tris * (t_pct / 100.0))) if base_tris > 0 else int(t_def.get("target_tris", 10000))
        )
        item.triangle_target = item.target_tris
        item.is_soloed = False
        item.is_impostor = bool(t_def.get("is_impostor", False))

        s_frac = s_pct / 100.0
        dist = compute_distance_from_screen_size(radius, s_frac, fov_v)
        item.distance_m = dist
        item.mat_slots_count = total_mat_slots if i < 2 else max(1, total_mat_slots - (i - 1))

        # State detection
        if i == 0:
            item.state = "SOURCE"
            item.actual_tris = base_tris
            item.actual_triangles = base_tris
            item.last_baked_target_pct = 100.0
            item.last_baked_screen_pct = 100.0
            if base_meshes:
                item.generated_obj = base_meshes[0]
        else:
            exist_info = existing_lods.get(i)
            if exist_info and exist_info.get("meshes"):
                item.actual_tris = exist_info.get("actual_tris", 0)
                item.actual_triangles = item.actual_tris
                cached_last = float(t_def.get("last_baked_target_pct", -1.0)) if cached_tiers else -1.0
                if cached_last > 0.0:
                    item.last_baked_target_pct = cached_last
                    item.last_baked_screen_pct = float(t_def.get("last_baked_screen_pct", s_pct))
                    if abs(t_pct - cached_last) > 0.01:
                        item.state = "OUT_OF_SYNC"
                    else:
                        item.state = "BAKED"
                else:
                    item.last_baked_target_pct = t_pct
                    item.last_baked_screen_pct = s_pct
                    item.state = "BAKED"
                item.generated_obj = exist_info["meshes"][0]
            else:
                item.state = "PLANNED"
                item.actual_tris = 0
                item.actual_triangles = 0
                item.last_baked_target_pct = -1.0
                item.last_baked_screen_pct = -1.0

    props.active_lod_index = 0


def on_lod_preset_updated(self: Any, context: Any) -> None:
    """Synchronizes active LOD preset choice and projects tiers onto current asset."""
    if StateRestorationGuard.is_active() or PresetSyncGuard.is_locked():
        return
    preset_id = getattr(self, "lod_preset", "")
    if not preset_id:
        return
    LODPresetManager.set_last_active_preset(preset_id)
    preset = LODPresetManager.get_preset(preset_id)
    sync_preset_tiers_from_preset(self, preset)
    try:
        project_preset_tiers(self, context, ignore_cache=True)
    except Exception as exc:
        logger.debug("Automatic tier projection skipped: %s", exc)


def on_lod_budget_mode_updated(self: Any, context: Any) -> None:
    """Updates active preset dirty state when budget mode is modified."""
    if StateRestorationGuard.is_active() or PresetSyncGuard.is_locked():
        return
    self.lod_preset_is_dirty = True


def get_pbr_import_preset_items(self: Any, context: Any) -> list[tuple[str, str, str]]:
    """Dynamic enum items for PBR Texture Set Importer Presets."""
    try:
        return PBRImportPresetManager.get_enum_items()
    except Exception:
        return [("unreal_engine_5", "Unreal Engine 5 (Packed ORM)", "Default template")]


def get_pbr_export_preset_items(self: Any, context: Any) -> list[tuple[str, str, str]]:
    """Dynamic enum items for Unified Engine Export Presets."""
    try:
        return PBRExportPresetManager.get_enum_items()
    except Exception:
        return [("unreal_engine_5", "Unreal Engine 5", "Default template")]


get_pbr_preset_items = get_pbr_export_preset_items


def get_engine_import_preset_items(self: Any, context: Any) -> list[tuple[str, str, str]]:
    """Dynamic enum items for Engine / Project Importer Presets."""
    try:
        return EngineImportPresetManager.get_enum_items()
    except Exception:
        return [(DEFAULT_ENGINE_IMPORT_PRESET_ID, "MSFS 2024 Aircraft", "MSFS 2024 Aircraft Project Importer")]


def on_engine_import_preset_updated(self: Any, context: Any) -> None:
    """Synchronizes active engine import preset selection with settings properties."""
    if StateRestorationGuard.is_active() or PresetSyncGuard.is_locked():
        return
    preset_id = getattr(self, "engine_import_preset", "")
    if not preset_id:
        return
    preset = EngineImportPresetManager.get_preset(preset_id)
    with PresetSyncGuard():
        if hasattr(self, "engine_import_geometry"):
            self.engine_import_geometry = bool(preset.get("import_geometry", True))
        if hasattr(self, "engine_import_spatial"):
            self.engine_import_spatial = bool(preset.get("import_spatial", True))
        if hasattr(self, "engine_import_lights"):
            self.engine_import_lights = bool(preset.get("import_lights", True))
        if hasattr(self, "engine_import_cameras"):
            self.engine_import_cameras = bool(preset.get("import_cameras", True))
        if hasattr(self, "engine_import_model_target"):
            self.engine_import_model_target = str(preset.get("model_target", "EXTERIOR_ONLY"))
        if hasattr(self, "engine_import_use_lod0_suffix"):
            self.engine_import_use_lod0_suffix = bool(preset.get("use_lod0_suffix", True))
        if hasattr(self, "engine_import_auto_assign_screen_pct"):
            self.engine_import_auto_assign_screen_pct = bool(preset.get("auto_assign_screen_pct", True))
        if hasattr(self, "engine_import_deduplicate_materials"):
            self.engine_import_deduplicate_materials = bool(preset.get("deduplicate_materials", True))
        if hasattr(self, "engine_import_reuse_master_rig"):
            self.engine_import_reuse_master_rig = bool(preset.get("reuse_master_rig", True))


def on_engine_import_directory_updated(self: Any, _context: Any) -> None:
    """Persists engine import directory path across sessions."""
    if StateRestorationGuard.is_active():
        return
    val = getattr(self, "engine_import_directory", "")
    try:
        set_pipeline_setting("engine_import_directory", val)
    except Exception as exc:
        logger.debug("Persist engine import directory: %s", exc)


def on_active_lod_index_updated(self: Any, context: Any) -> None:
    """Updates HUD monitor and tags redraw when active LOD tier changes."""
    if StateRestorationGuard.is_active():
        return
    try:
        from ..hud import LODViewportHUD

        LODViewportHUD.update_cache(context)
        LODViewportHUD.tag_redraw()
    except Exception as exc:
        logger.debug("Active LOD index HUD update exception: %s", exc)


__all__ = [
    "ENGINE_TO_FACTORY_PRESET",
    "update_bridge_status_cached",
    "on_target_engine_updated",
    "on_export_preset_updated",
    "on_import_preset_updated",
    "on_legacy_preset_updated",
    "on_export_strategy_updated",
    "on_export_bit_depth_updated",
    "on_export_naming_updated",
    "on_import_directory_updated",
    "on_import_path_mode_updated",
    "on_export_directory_updated",
    "on_import_ao_mode_updated",
    "on_import_preserve_updated",
    "on_engine_project_path_updated",
    "on_enable_live_sync_updated",
    "on_batch_mode_updated",
    "on_batch_source_updated",
    "restore_preset_state_on_load",
    "get_lod_preset_items",
    "project_preset_tiers",
    "on_lod_preset_updated",
    "on_lod_budget_mode_updated",
    "get_pbr_import_preset_items",
    "get_pbr_export_preset_items",
    "get_pbr_preset_items",
    "get_engine_import_preset_items",
    "on_engine_import_preset_updated",
    "on_engine_import_directory_updated",
    "on_active_lod_index_updated",
]
