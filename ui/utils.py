"""
Shared UI utilities and context resolvers for OmniMesh operators and panels.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bpy
except ImportError:
    bpy = None


def is_object_valid(obj: Any) -> bool:
    """Safely check if a Blender object exists and is not freed/invalidated."""
    if obj is None:
        return False
    try:
        _ = getattr(obj, "name", None)
        return True
    except (ReferenceError, AttributeError):
        return False


def get_selected_mesh_objects(context: Any) -> list[Any]:
    """Retrieve all valid, non-collider, non-impostor MESH objects from selection or active object."""
    if not context:
        return []
    objs = context.selected_objects if hasattr(context, "selected_objects") else []
    if not objs and getattr(context, "active_object", None):
        objs = [context.active_object]

    raw_meshes = []
    for obj in objs:
        if not is_object_valid(obj):
            continue
        if getattr(obj, "type", "") == "MESH":
            name = getattr(obj, "name", "")
            is_col = bool(getattr(obj, "get", lambda *_: False)("_is_collider", False) is True)
            if not is_col and not name.startswith("UCX_"):
                raw_meshes.append(obj)

    base_meshes = [obj for obj in raw_meshes if not any(f"_LOD{n}" in getattr(obj, "name", "") for n in range(1, 11))]
    return base_meshes if base_meshes else raw_meshes


def get_associated_armature(mesh_objs: list[Any]) -> Any:
    """Find armature parent or modifier attached to any of the provided mesh objects."""
    for obj in mesh_objs:
        if not is_object_valid(obj):
            continue
        if (
            getattr(obj, "parent", None)
            and is_object_valid(obj.parent)
            and getattr(obj.parent, "type", "") == "ARMATURE"
        ):
            return obj.parent
        for mod in getattr(obj, "modifiers", []):
            if getattr(mod, "type", "") == "ARMATURE" and is_object_valid(getattr(mod, "object", None)):
                return mod.object
    return None


def resolve_lod_context(context: Any) -> tuple[Any, Any | None, bool]:
    """
    Context Resolver: returns (active_settings, master_object_or_coll, is_derivative_lod).
    """
    if not context:
        return None, None, False

    scene_props = getattr(getattr(context, "scene", None), "lod_tool", None)
    active_obj = getattr(context, "active_object", None)

    if not active_obj or getattr(active_obj, "type", "") != "MESH":
        return scene_props, None, False

    obj_props = getattr(active_obj, "lod_tool", None)
    if not obj_props:
        return scene_props, active_obj, False

    if bool(getattr(obj_props, "is_generated_lod", False) is True):
        master_name = getattr(obj_props, "lod_root_object", "")
        master_obj = bpy.data.objects.get(master_name) if bpy and master_name else None
        if master_obj and hasattr(master_obj, "lod_tool"):
            return master_obj.lod_tool, master_obj, True
        return obj_props, active_obj, True

    is_cfg = bool(getattr(obj_props, "is_configured", False) is True)
    return (obj_props if is_cfg else scene_props), active_obj, False


def safe_report(operator: Any, msg_type: set[str], msg: str) -> None:
    """Safely report status message from an operator with headless fallback."""
    if hasattr(operator, "report"):
        try:
            operator.report(msg_type, msg)
        except Exception:
            logger.debug("[%s] %s", msg_type, msg)
    else:
        logger.debug("[%s] %s", msg_type, msg)
