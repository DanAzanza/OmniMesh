"""
OmniMesh Properties Package.
Maintains data models for LOD tiers, screen metrics, collision hulls, rigging, PBR textures,
engine presets, mesh cleanup, material cleanup, impostors, PBR importer, live simulation, and live engine bridges.
"""

import logging

try:
    import bpy
    from bpy.props import PointerProperty
except ImportError:
    bpy = None
    PointerProperty = None

logger = logging.getLogger(__name__)

# Relative imports from submodules
from . import callbacks, enums, guards, lod_properties, pbr_properties, settings
from .callbacks import (
    ENGINE_TO_FACTORY_PRESET,
    get_lod_preset_items,
    get_pbr_export_preset_items,
    get_pbr_import_preset_items,
    get_pbr_preset_items,
    on_active_lod_index_updated,
    on_batch_mode_updated,
    on_batch_source_updated,
    on_enable_live_sync_updated,
    on_engine_project_path_updated,
    on_export_bit_depth_updated,
    on_export_directory_updated,
    on_export_naming_updated,
    on_export_preset_updated,
    on_export_strategy_updated,
    on_import_ao_mode_updated,
    on_import_directory_updated,
    on_import_path_mode_updated,
    on_import_preserve_updated,
    on_import_preset_updated,
    on_legacy_preset_updated,
    on_lod_budget_mode_updated,
    on_lod_preset_updated,
    on_target_engine_updated,
    project_preset_tiers,
    restore_preset_state_on_load,
    update_bridge_status_cached,
)
from .guards import (
    ExportMapSyncGuard,
    MapSyncGuard,
    PresetSyncGuard,
    StateRestorationGuard,
)
from .lod_properties import (
    LODLevelItem,
    LODPresetTierItem,
    on_lod_preset_property_modified,
    on_preset_tier_item_updated,
    on_split_preview_updated,
    on_tier_target_pct_updated,
    on_tier_target_tris_updated,
    sync_preset_tiers_from_preset,
    sync_preset_tiers_to_preset,
)
from .pbr_properties import (
    PRINCIPLED_TARGET_ITEMS,
    PBRExportMapItem,
    PBRMapItem,
    on_export_map_item_updated,
    on_map_item_updated,
    sync_export_maps_from_preset,
    sync_export_maps_to_preset,
    sync_maps_from_preset,
    sync_maps_to_preset,
)
from .settings import LODToolSettings

# Dynamic reload sequence in strict dependency order
if "_OMNIMESH_PROPERTIES_LOADED" in locals():
    import importlib

    for mod in (enums, guards, lod_properties, pbr_properties, callbacks, settings):
        importlib.reload(mod)
_OMNIMESH_PROPERTIES_LOADED = True

CLASSES = (
    LODLevelItem,
    LODPresetTierItem,
    PBRMapItem,
    PBRExportMapItem,
    LODToolSettings,
)


def register_properties() -> None:
    if not bpy:
        return
    for cls in CLASSES:
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:
            logger.debug("Safe unregister skipped %s: %s", getattr(cls, "__name__", "cls"), exc)
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            logger.debug("Safe register skipped %s: %s", getattr(cls, "__name__", "cls"), exc)
    try:
        bpy.types.Scene.lod_tool = PointerProperty(type=LODToolSettings)
        bpy.types.Object.lod_tool = PointerProperty(type=LODToolSettings)
    except Exception as exc:
        logger.debug("PointerProperty assignment exception: %s", exc)

    if restore_preset_state_on_load and hasattr(bpy, "app") and hasattr(bpy.app, "handlers"):
        if hasattr(bpy.app.handlers, "load_post"):
            if restore_preset_state_on_load not in bpy.app.handlers.load_post:
                bpy.app.handlers.load_post.append(restore_preset_state_on_load)
        try:
            restore_preset_state_on_load(None)
        except Exception as exc:
            logger.debug("Immediate preset restore exception: %s", exc)


def unregister_properties() -> None:
    if not bpy:
        return
    if restore_preset_state_on_load and hasattr(bpy, "app") and hasattr(bpy.app, "handlers"):
        if hasattr(bpy.app.handlers, "load_post") and restore_preset_state_on_load in bpy.app.handlers.load_post:
            try:
                bpy.app.handlers.load_post.remove(restore_preset_state_on_load)
            except (ValueError, KeyError, AttributeError) as exc:
                logger.debug("Handler removal skipped: %s", exc)
    if hasattr(bpy.types.Scene, "lod_tool"):
        del bpy.types.Scene.lod_tool
    if hasattr(bpy.types.Object, "lod_tool"):
        del bpy.types.Object.lod_tool
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


__all__ = [
    "CLASSES",
    "register_properties",
    "unregister_properties",
    "PresetSyncGuard",
    "StateRestorationGuard",
    "MapSyncGuard",
    "ExportMapSyncGuard",
    "LODLevelItem",
    "LODPresetTierItem",
    "PBRMapItem",
    "PBRExportMapItem",
    "LODToolSettings",
    "PRINCIPLED_TARGET_ITEMS",
    "ENGINE_TO_FACTORY_PRESET",
    "on_tier_target_pct_updated",
    "on_tier_target_tris_updated",
    "on_preset_tier_item_updated",
    "on_lod_preset_property_modified",
    "on_split_preview_updated",
    "sync_preset_tiers_from_preset",
    "sync_preset_tiers_to_preset",
    "on_map_item_updated",
    "sync_maps_from_preset",
    "sync_maps_to_preset",
    "on_export_map_item_updated",
    "sync_export_maps_from_preset",
    "sync_export_maps_to_preset",
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
    "on_active_lod_index_updated",
]
