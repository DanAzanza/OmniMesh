"""
OmniMesh Preset CRUD & Management Operators Hub.
Aggregates and re-exports PBR and LOD tier preset management operators.
"""

from __future__ import annotations

try:
    from .lod_preset_ops import (
        LOD_PRESET_OPERATOR_CLASSES,
        LOD_OT_add_preset_tier,
        LOD_OT_apply_preset_tiers,
        LOD_OT_capture_scene_tiers,
        LOD_OT_delete_lod_preset,
        LOD_OT_remove_preset_tier,
        LOD_OT_save_preset_tiers,
    )
    from .pbr_preset_ops import (
        PBR_PRESET_OPERATOR_CLASSES,
        LOD_OT_add_export_preset_map,
        LOD_OT_add_preset_map,
        LOD_OT_delete_export_preset,
        LOD_OT_delete_export_preset_map,
        LOD_OT_delete_import_preset,
        LOD_OT_delete_preset_map,
        LOD_OT_duplicate_export_preset,
        LOD_OT_duplicate_preset,
        LOD_OT_open_presets_directory,
        LOD_OT_reload_pbr_presets,
        LOD_OT_reset_pbr_preset,
        LOD_OT_save_export_preset,
    )
except (ImportError, ValueError):
    from ui.lod_preset_ops import (
        LOD_PRESET_OPERATOR_CLASSES,
        LOD_OT_add_preset_tier,
        LOD_OT_apply_preset_tiers,
        LOD_OT_capture_scene_tiers,
        LOD_OT_delete_lod_preset,
        LOD_OT_remove_preset_tier,
        LOD_OT_save_preset_tiers,
    )
    from ui.pbr_preset_ops import (
        PBR_PRESET_OPERATOR_CLASSES,
        LOD_OT_add_export_preset_map,
        LOD_OT_add_preset_map,
        LOD_OT_delete_export_preset,
        LOD_OT_delete_export_preset_map,
        LOD_OT_delete_import_preset,
        LOD_OT_delete_preset_map,
        LOD_OT_duplicate_export_preset,
        LOD_OT_duplicate_preset,
        LOD_OT_open_presets_directory,
        LOD_OT_reload_pbr_presets,
        LOD_OT_reset_pbr_preset,
        LOD_OT_save_export_preset,
    )

PRESET_OPERATOR_CLASSES = (
    *PBR_PRESET_OPERATOR_CLASSES,
    *LOD_PRESET_OPERATOR_CLASSES,
)

__all__ = [
    "PRESET_OPERATOR_CLASSES",
    "PBR_PRESET_OPERATOR_CLASSES",
    "LOD_PRESET_OPERATOR_CLASSES",
    "LOD_OT_reload_pbr_presets",
    "LOD_OT_reset_pbr_preset",
    "LOD_OT_duplicate_preset",
    "LOD_OT_duplicate_export_preset",
    "LOD_OT_add_preset_map",
    "LOD_OT_delete_preset_map",
    "LOD_OT_add_export_preset_map",
    "LOD_OT_delete_export_preset_map",
    "LOD_OT_open_presets_directory",
    "LOD_OT_save_export_preset",
    "LOD_OT_delete_import_preset",
    "LOD_OT_delete_export_preset",
    "LOD_OT_delete_lod_preset",
    "LOD_OT_add_preset_tier",
    "LOD_OT_remove_preset_tier",
    "LOD_OT_save_preset_tiers",
    "LOD_OT_apply_preset_tiers",
    "LOD_OT_capture_scene_tiers",
]
