"""
OmniMesh LOD Tier Preset CRUD & Management Operators.
Handles adding, removing, saving, applying, capturing, and deleting
LOD tier templates and custom presets.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from ..core.lod_presets import (
        DEFAULT_LOD_PRESET_ID,
        LODPresetManager,
    )
    from .properties import (
        sync_preset_tiers_from_preset,
        sync_preset_tiers_to_preset,
    )
    from .utils import resolve_lod_context, safe_report
except (ImportError, ValueError):
    from core.lod_presets import (
        DEFAULT_LOD_PRESET_ID,
        LODPresetManager,
    )
    from ui.properties import (
        sync_preset_tiers_from_preset,
        sync_preset_tiers_to_preset,
    )
    from ui.utils import resolve_lod_context, safe_report

try:
    import bpy
    from bpy.types import Operator
except ImportError:
    bpy = None
    Operator = object

logger = logging.getLogger(__name__)


class LOD_OT_delete_lod_preset(Operator):
    """Permanently delete active custom LOD preset and cleanly reset to factory default."""

    bl_idname = "lod_tool.delete_lod_preset"
    bl_label = "Delete Custom Preset"
    bl_description = "Deletes the active custom LOD preset file and resets to factory default"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context: Any, event: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
        if not props:
            props, _, _ = resolve_lod_context(context)
        preset_id = getattr(props, "lod_preset", "") or DEFAULT_LOD_PRESET_ID
        if not LODPresetManager.is_user_preset(preset_id):
            safe_report(self, {"ERROR"}, "Cannot delete unmodified factory presets.")
            return {"CANCELLED"}
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context: Any) -> set[str]:
        targets = []
        if context and hasattr(context, "scene") and hasattr(context.scene, "lod_tool"):
            targets.append(context.scene.lod_tool)
        obj_props, _, _ = resolve_lod_context(context)
        if obj_props and obj_props not in targets:
            targets.append(obj_props)

        props = targets[0] if targets else None
        preset_id = getattr(props, "lod_preset", "") or DEFAULT_LOD_PRESET_ID

        if not LODPresetManager.is_user_preset(preset_id):
            safe_report(self, {"ERROR"}, "Cannot delete unmodified factory presets.")
            return {"CANCELLED"}

        try:
            is_shipped_template = (LODPresetManager.get_builtin_dir() / f"{preset_id}.json").is_file()
            fallback_id = preset_id if is_shipped_template else LODPresetManager.DEFAULT_PRESET_ID
            for p in targets:
                if hasattr(p, "lod_preset") and p.lod_preset == preset_id:
                    p.lod_preset = fallback_id

            success = LODPresetManager.delete_custom_preset(preset_id)
            if success:
                for p in targets:
                    active_pid = getattr(p, "lod_preset", fallback_id)
                    restored = LODPresetManager.get_preset(active_pid)
                    sync_preset_tiers_from_preset(p, restored)

                msg = (
                    f"Reset LOD preset '{preset_id}' to factory defaults."
                    if is_shipped_template
                    else f"Deleted custom LOD preset '{preset_id}'."
                )
                safe_report(self, {"INFO"}, msg)
                return {"FINISHED"}
            safe_report(self, {"WARNING"}, f"Could not find or delete LOD preset '{preset_id}'.")
            return {"CANCELLED"}
        except Exception as exc:
            logger.error("Failed to delete custom LOD preset '%s': %s", preset_id, exc, exc_info=True)
            safe_report(self, {"ERROR"}, f"Delete failed: {exc}")
            return {"CANCELLED"}


class LOD_OT_add_preset_tier(Operator):
    """Append a new tier template to the active LOD preset."""

    bl_idname = "lod_tool.add_preset_tier"
    bl_label = "Add Preset Tier"
    bl_description = "Appends a new tier template to the current preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        if len(props.lod_preset_active_tiers) >= 8:
            safe_report(self, {"WARNING"}, "Maximum 8 LOD tiers supported in a preset.")
            return {"CANCELLED"}

        count = len(props.lod_preset_active_tiers)
        prev = props.lod_preset_active_tiers[count - 1] if count > 0 else None

        item = props.lod_preset_active_tiers.add()
        item.name = f"LOD{count}"
        item.screen_size_pct = max(0.1, round(prev.screen_size_pct * 0.5, 1)) if prev else 100.0
        item.target_tris_pct = max(0.01, round(prev.target_tris_pct * 0.5, 2)) if prev else 100.0
        item.target_tris = max(6, int(prev.target_tris * 0.5)) if prev else 100000

        props.lod_preset_active_tier_index = count
        props.lod_preset_is_dirty = True
        safe_report(self, {"INFO"}, f"Added preset tier {item.name}.")
        return {"FINISHED"}


class LOD_OT_remove_preset_tier(Operator):
    """Remove the selected tier template from the active LOD preset."""

    bl_idname = "lod_tool.remove_preset_tier"
    bl_label = "Remove Preset Tier"
    bl_description = "Removes the selected tier template from the current preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        count = len(props.lod_preset_active_tiers)
        if count <= 1:
            safe_report(self, {"WARNING"}, "A preset must contain at least one LOD tier.")
            return {"CANCELLED"}

        idx = props.lod_preset_active_tier_index
        if idx < 0 or idx >= count:
            idx = count - 1

        deleted_name = props.lod_preset_active_tiers[idx].name
        props.lod_preset_active_tiers.remove(idx)
        props.lod_preset_active_tier_index = max(0, min(idx, len(props.lod_preset_active_tiers) - 1))
        props.lod_preset_is_dirty = True
        safe_report(self, {"INFO"}, f"Removed preset tier {deleted_name}.")
        return {"FINISHED"}


class LOD_OT_save_preset_tiers(Operator):
    """Save modified tier configuration into the custom LOD preset on disk."""

    bl_idname = "lod_tool.save_preset_tiers"
    bl_label = "Save Preset Tiers"
    bl_description = "Saves tier screensizes and budgets to the custom preset JSON file"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        try:
            saved_id = sync_preset_tiers_to_preset(props)
            safe_report(self, {"INFO"}, f"Saved tiers to preset '{saved_id}'.")
            return {"FINISHED"}
        except Exception as exc:
            logger.error("Failed saving preset tiers: %s", exc, exc_info=True)
            safe_report(self, {"ERROR"}, f"Save failed: {exc}")
            return {"CANCELLED"}


class LOD_OT_apply_preset_tiers(Operator):
    """Apply preset tier definitions to the scene and recalculate transition distances."""

    bl_idname = "lod_tool.apply_preset_tiers"
    bl_label = "Apply to Scene"
    bl_description = "Applies preset tier definitions to the scene and updates switch distances"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        return bpy.ops.lod_tool.analyze_and_configure()


class LOD_OT_capture_scene_tiers(Operator):
    """Capture current active scene LOD tiers into the preset tier template."""

    bl_idname = "lod_tool.capture_scene_tiers"
    bl_label = "Capture Scene Tiers"
    bl_description = "Captures the active scene LOD tiers into the preset template"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        if not props.lods:
            safe_report(self, {"WARNING"}, "No active scene LOD tiers to capture.")
            return {"CANCELLED"}

        props.lod_preset_active_tiers.clear()
        for tier in props.lods:
            item = props.lod_preset_active_tiers.add()
            item.name = tier.name
            item.screen_size_pct = tier.screen_size_pct
            item.target_tris_pct = tier.target_tris_pct
            item.target_tris = tier.target_tris

        props.lod_preset_is_dirty = True
        safe_report(self, {"INFO"}, f"Captured {len(props.lods)} tiers from scene.")
        return {"FINISHED"}


LOD_PRESET_OPERATOR_CLASSES = (
    LOD_OT_delete_lod_preset,
    LOD_OT_add_preset_tier,
    LOD_OT_remove_preset_tier,
    LOD_OT_save_preset_tiers,
    LOD_OT_apply_preset_tiers,
    LOD_OT_capture_scene_tiers,
)

__all__ = [
    "LOD_PRESET_OPERATOR_CLASSES",
    "LOD_OT_delete_lod_preset",
    "LOD_OT_add_preset_tier",
    "LOD_OT_remove_preset_tier",
    "LOD_OT_save_preset_tiers",
    "LOD_OT_apply_preset_tiers",
    "LOD_OT_capture_scene_tiers",
]
