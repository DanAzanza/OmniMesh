"""
OmniMesh Central User Operators Coordinator and Registration Hub.
Modularized into single-responsibility submodules:
- ui.utils: Context resolvers and object queries
- ui.cleanup_ops: Preflight inspection, topology repair, and material hygiene
- ui.lod_ops: LOD configuration, generation, tier preview, and selection sync
- ui.hull_impostor_ops: Collision decomposition hulls and billboard impostors
- ui.pbr_ops: PBR texture set importing and folder auto-matching
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import bpy
except ImportError:
    bpy = None

try:
    from ui.chunk_ops import (
        CLASSES as CHUNK_OPERATOR_CLASSES,
        LOD_OT_spatial_chunk_and_generate,
        LOD_OT_voxel_scan_cleanup,
    )
    from ui.cleanup_ops import (
        CLEANUP_OPERATOR_CLASSES,
        LOD_OT_apply_all_modifiers,
        LOD_OT_apply_transforms,
        LOD_OT_clean_and_repair_materials,
        LOD_OT_clean_and_repair_mesh,
        LOD_OT_inspect_lod0,
    )
    from ui.hull_impostor_ops import (
        HULL_IMPOSTOR_OPERATOR_CLASSES,
        LOD_OT_generate_collision_hulls,
        LOD_OT_generate_impostor,
        LOD_OT_remove_collision_hulls,
        LOD_OT_remove_impostor,
    )
    from ui.lod_ops import (
        LOD_OPERATOR_CLASSES,
        LOD_OT_analyze_and_configure,
        LOD_OT_generate_all,
        LOD_OT_preview_tier,
        LOD_OT_select_master_asset,
        LOD_OT_sync_selection_settings,
    )
    from ui.pbr_ops import (
        PBR_OPERATOR_CLASSES,
        LOD_OT_auto_match_pbr_folder,
        LOD_OT_import_pbr_set,
    )
    from ui.simulator_ops import LOD_OT_toggle_simulator
    from ui.split_preview import OMNIMESH_OT_toggle_split_preview as LOD_OT_toggle_split_preview
    from ui.utils import (
        get_associated_armature,
        get_selected_mesh_objects,
        is_object_valid,
        resolve_lod_context,
    )
except (ImportError, ValueError):
    from .chunk_ops import (
        CLASSES as CHUNK_OPERATOR_CLASSES,
        LOD_OT_spatial_chunk_and_generate,
        LOD_OT_voxel_scan_cleanup,
    )
    from .cleanup_ops import (
        CLEANUP_OPERATOR_CLASSES,
        LOD_OT_apply_all_modifiers,
        LOD_OT_apply_transforms,
        LOD_OT_clean_and_repair_materials,
        LOD_OT_clean_and_repair_mesh,
        LOD_OT_inspect_lod0,
    )
    from .hull_impostor_ops import (
        HULL_IMPOSTOR_OPERATOR_CLASSES,
        LOD_OT_generate_collision_hulls,
        LOD_OT_generate_impostor,
        LOD_OT_remove_collision_hulls,
        LOD_OT_remove_impostor,
    )
    from .lod_ops import (
        LOD_OPERATOR_CLASSES,
        LOD_OT_analyze_and_configure,
        LOD_OT_generate_all,
        LOD_OT_preview_tier,
        LOD_OT_select_master_asset,
        LOD_OT_sync_selection_settings,
    )
    from .pbr_ops import (
        PBR_OPERATOR_CLASSES,
        LOD_OT_auto_match_pbr_folder,
        LOD_OT_import_pbr_set,
    )
    from .simulator_ops import LOD_OT_toggle_simulator
    from .split_preview import OMNIMESH_OT_toggle_split_preview as LOD_OT_toggle_split_preview
    from .utils import (
        get_associated_armature,
        get_selected_mesh_objects,
        is_object_valid,
        resolve_lod_context,
    )

OPERATOR_CLASSES = [
    *CLEANUP_OPERATOR_CLASSES,
    *LOD_OPERATOR_CLASSES,
    *HULL_IMPOSTOR_OPERATOR_CLASSES,
    *PBR_OPERATOR_CLASSES,
    *CHUNK_OPERATOR_CLASSES,
]


def register_operators() -> None:
    if not bpy:
        return
    for cls in OPERATOR_CLASSES:
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:
            logger.debug("Safe unregister skipped %s: %s", getattr(cls, "__name__", "cls"), exc)
        bpy.utils.register_class(cls)


def unregister_operators() -> None:
    if not bpy:
        return
    for cls in reversed(OPERATOR_CLASSES):
        bpy.utils.unregister_class(cls)


__all__ = [
    "is_object_valid",
    "get_selected_mesh_objects",
    "get_associated_armature",
    "resolve_lod_context",
    "LOD_OT_inspect_lod0",
    "LOD_OT_analyze_and_configure",
    "LOD_OT_generate_all",
    "LOD_OT_generate_impostor",
    "LOD_OT_remove_impostor",
    "LOD_OT_generate_collision_hulls",
    "LOD_OT_remove_collision_hulls",
    "LOD_OT_preview_tier",
    "LOD_OT_toggle_simulator",
    "LOD_OT_toggle_split_preview",
    "LOD_OT_clean_and_repair_mesh",
    "LOD_OT_clean_and_repair_materials",
    "LOD_OT_apply_all_modifiers",
    "LOD_OT_apply_transforms",
    "LOD_OT_import_pbr_set",
    "LOD_OT_auto_match_pbr_folder",
    "LOD_OT_sync_selection_settings",
    "LOD_OT_select_master_asset",
    "LOD_OT_spatial_chunk_and_generate",
    "LOD_OT_voxel_scan_cleanup",
    "OPERATOR_CLASSES",
    "register_operators",
    "unregister_operators",
]
