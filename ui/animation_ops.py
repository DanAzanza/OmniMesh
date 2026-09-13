"""
OmniMesh Animation & Action Tagging Operators.
Exposes UI operators for tagging active Blender Actions with semantic categories
(Landing Gear, Controls, Doors, Cockpit, Propellers) and generating MSFS XML definitions.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bpy
    from bpy.types import Operator
except ImportError:
    bpy = None
    Operator = object

try:
    from ..core.animation_manager import scan_asset_animations, tag_action_category
    from .utils import resolve_effective_asset_name, safe_report
except (ImportError, ValueError):
    from core.animation_manager import scan_asset_animations, tag_action_category
    from ui.utils import resolve_effective_asset_name, safe_report


class OMNIMESH_OT_tag_animation(Operator):
    """Tags the active object's current Action with the selected semantic category and GUID."""

    bl_idname = "omnimesh.tag_animation"
    bl_label = "Tag Active Action"
    bl_description = (
        "Tags active Action with semantic category (Gear, Control, Door, Cockpit) "
        "and generates deterministic GUID for multi-engine export and MSFS ModelInfo.xml"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        if not bpy or not context:
            return False
        active = getattr(context, "active_object", None)
        if not active or not getattr(active, "animation_data", None):
            return False
        return bool(getattr(active.animation_data, "action", None))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}

        active = context.active_object
        action = active.animation_data.action
        act_name = getattr(action, "name", "")

        props = getattr(context.scene, "lod_tool", None) if context else None
        anim_props = getattr(props, "animation_tagging", None) if props else None

        category = getattr(anim_props, "semantic_category", "GENERIC") if anim_props else "GENERIC"
        custom_guid = getattr(anim_props, "custom_guid", "") if anim_props else ""

        ok = tag_action_category(act_name, category, custom_guid if custom_guid else None)
        if ok:
            guid = action.get("_omnimesh_guid", "")
            safe_report(self, {"INFO"}, f"Tagged Action '{act_name}' as {category} [GUID: {guid[:8]}...]")
            return {"FINISHED"}

        safe_report(self, {"WARNING"}, f"Could not tag Action '{act_name}'.")
        return {"CANCELLED"}


class OMNIMESH_OT_scan_animations(Operator):
    """Scans and reports all Actions and NLA tracks associated with the active asset."""

    bl_idname = "omnimesh.scan_animations"
    bl_label = "Scan Asset Animations"
    bl_description = "Discovers all animation tracks on active asset armatures and animated meshes"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(bpy and context)

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}

        props = getattr(context.scene, "lod_tool", None) if context else None
        asset_name = resolve_effective_asset_name(context, props)
        if not asset_name or asset_name in ("AUTO", "NONE"):
            asset_name = "Asset"

        actions = scan_asset_animations(context, asset_name)
        if not actions:
            safe_report(self, {"INFO"}, f"No animation actions found on asset '{asset_name}'.")
            return {"FINISHED"}

        summary = ", ".join(f"{a['sanitized_name']} ({a['category']})" for a in actions[:3])
        if len(actions) > 3:
            summary += f" + {len(actions) - 3} more"

        safe_report(self, {"INFO"}, f"Found {len(actions)} action(s) on '{asset_name}': {summary}")
        return {"FINISHED"}


ANIMATION_OPERATOR_CLASSES = (
    OMNIMESH_OT_tag_animation,
    OMNIMESH_OT_scan_animations,
)


def register():
    if not bpy:
        return
    for cls in ANIMATION_OPERATOR_CLASSES:
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            logger.debug("Register skipped %s: %s", getattr(cls, "__name__", "cls"), exc)


def unregister():
    if not bpy:
        return
    for cls in reversed(ANIMATION_OPERATOR_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:
            logger.debug("Unregister skipped %s: %s", getattr(cls, "__name__", "cls"), exc)
