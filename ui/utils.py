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


def get_lod0_mesh_objects(context: Any, base_name: str = "") -> list[Any]:
    """
    Retrieve all true LOD0 source MESH objects for the active asset or selection.

    1. If objects reside in an asset collection ({BaseName}, {BaseName}_LOD0),
       all non-collider, non-impostor MESH objects in that collection are returned,
       even if only a single object or sub-component was selected.
    2. If the user currently has a derivative LOD active (_LOD1.._LOD10), automatically
       resolves back to the primary LOD0 meshes.
    3. Falls back safely to selected base meshes.
    """
    if not context:
        return []

    active_obj = getattr(context, "active_object", None)
    selected_objs = getattr(context, "selected_objects", []) or ([active_obj] if active_obj else [])

    if not base_name:
        props = getattr(getattr(context, "scene", None), "lod_tool", None)
        base_name = getattr(props, "export_base_name", "") or ""

    if not base_name and active_obj:
        raw_name = getattr(active_obj, "name", "")
        base_name = raw_name.split("_LOD")[0].split("_Collider")[0].split("_Impostor")[0]

    if not base_name and selected_objs:
        raw_name = getattr(selected_objs[0], "name", "")
        base_name = raw_name.split("_LOD")[0].split("_Collider")[0].split("_Impostor")[0]

    # 1. Search for asset root collection
    candidate_coll = None
    if bpy and hasattr(bpy, "data") and hasattr(bpy.data, "collections") and base_name:
        for c_name in (f"{base_name}_LOD0", base_name):
            c = bpy.data.collections.get(c_name)
            if c and getattr(context, "scene", None) and c != context.scene.collection:
                candidate_coll = c
                break

    if not candidate_coll and active_obj and hasattr(active_obj, "users_collection"):
        for c in active_obj.users_collection:
            if getattr(context, "scene", None) and c == context.scene.collection:
                continue
            c_name = getattr(c, "name", "")
            if "_Colliders" in c_name or "_Impostor" in c_name:
                continue
            root_c_name = c_name
            for n in range(0, 11):
                root_c_name = root_c_name.split(f"_LOD{n}")[0]
            root_c = None
            if bpy and hasattr(bpy, "data") and hasattr(bpy.data, "collections"):
                root_c = bpy.data.collections.get(root_c_name) or bpy.data.collections.get(f"{root_c_name}_LOD0")
            if root_c:
                candidate_coll = root_c
                break
            if not any(f"_LOD{n}" in c_name for n in range(1, 11)):
                candidate_coll = c
                break

    if candidate_coll and hasattr(candidate_coll, "objects"):
        coll_meshes = []
        for obj in candidate_coll.objects:
            if not is_object_valid(obj) or getattr(obj, "type", "") != "MESH":
                continue
            name = getattr(obj, "name", "")
            is_col = bool(getattr(obj, "get", lambda *_: False)("_is_collider", False) is True)
            is_imp = bool(getattr(obj, "get", lambda *_: False)("_is_impostor", False) is True)
            if is_col or is_imp or name.startswith("UCX_") or "_Collider_" in name:
                continue
            if any(f"_LOD{n}" in name for n in range(1, 11)):
                continue
            coll_meshes.append(obj)
        if coll_meshes:
            return coll_meshes

    # 2. Fallback: inspect selected meshes and resolve any _LOD1..10 back to LOD0
    selected_meshes = get_selected_mesh_objects(context)
    if not selected_meshes:
        return []

    lod0_resolved: list[Any] = []
    if bpy and hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
        for obj in selected_meshes:
            name = getattr(obj, "name", "")
            if any(f"_LOD{n}" in name for n in range(1, 11)):
                stem = name.split("_LOD")[0]
                lod0_obj = bpy.data.objects.get(f"{stem}_LOD0") or bpy.data.objects.get(stem)
                if lod0_obj and getattr(lod0_obj, "type", "") == "MESH" and is_object_valid(lod0_obj):
                    lod0_resolved.append(lod0_obj)
                else:
                    lod0_resolved.append(obj)
            else:
                lod0_resolved.append(obj)
        return lod0_resolved

    return selected_meshes


def resolve_asset_base_name(context: Any, mesh_objs: list[Any] | None = None) -> str:
    """
    Resolve asset root name:
    1. Central state override: props.export_base_name
    2. Sibling/parent asset collection name (excluding Scene Collection, _LOD1..10, _Colliders, _Impostor)
    3. Active mesh object or first mesh object name
    Strips suffixes (_LOD*, _Collider*, _Impostor).
    """
    if not context:
        return "Asset"

    props = getattr(getattr(context, "scene", None), "lod_tool", None)
    base_override = getattr(props, "export_base_name", "") or ""
    if base_override:
        return base_override.split("_LOD")[0].split("_Collider")[0].split("_Impostor")[0]

    active_obj = getattr(context, "active_object", None) or (mesh_objs[0] if mesh_objs else None)
    if active_obj and hasattr(active_obj, "users_collection"):
        for c in active_obj.users_collection:
            if getattr(context, "scene", None) and c == context.scene.collection:
                continue
            c_name = getattr(c, "name", "")
            if "_Colliders" in c_name or "_Impostor" in c_name:
                continue
            stem = c_name
            for n in range(0, 11):
                stem = stem.split(f"_LOD{n}")[0]
            if stem:
                return stem

    if active_obj:
        raw_name = getattr(active_obj, "name", "")
        return raw_name.split("_LOD")[0].split("_Collider")[0].split("_Impostor")[0]

    return "Asset"


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
