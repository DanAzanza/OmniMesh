"""
OmniMesh Multi-Engine Animation & Action Tagging Manager.
Discovers, sanitizes, and categorizes Blender Actions and NLA tracks on active assets,
ensuring clean cross-engine export (glTF/FBX) and deterministic MSFS ModelInfo XML
<Animation> and <PartInfo> generation without broken GUID references.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import bpy
    from bpy.types import Action, Object
except ImportError:
    bpy = None
    Action = object
    Object = object

try:
    from .animations import AnimationRigSanitizer
except (ImportError, ValueError):
    from core.animations import AnimationRigSanitizer


SIMVAR_MAPPINGS: dict[str, str] = {
    "LANDING_GEAR": "GEAR TOTAL PCT EXTENDED",
    "FLIGHT_CONTROL": "AILERON POSITION",
    "DOOR": "CANOPY OPEN",
    "COCKPIT_CONTROL": "GENERAL ENG THROTTLE LEVER POSITION:1",
    "PROP_BLUR": "PROP ROTATION ANGLE:1",
    "GENERIC": "TIME OF DAY",
}


def scan_asset_animations(context: Any, asset_name: str) -> list[dict[str, Any]]:
    """
    Scans armatures and animated meshes associated with the given asset,
    returning detailed metadata for all actions and NLA tracks.
    """
    if not bpy:
        return []

    clean_asset = str(asset_name).strip() or "Asset"
    discovered_actions: dict[str, dict[str, Any]] = {}

    target_objects: list[Any] = []
    if hasattr(bpy.data, "collections"):
        root_col = bpy.data.collections.get(clean_asset)
        if root_col and hasattr(root_col, "all_objects"):
            target_objects = list(root_col.all_objects)

    if not target_objects and hasattr(bpy.data, "objects"):
        for obj in bpy.data.objects:
            o_name = getattr(obj, "name", "")
            if o_name == clean_asset or o_name.startswith(f"{clean_asset}_"):
                target_objects.append(obj)

    for obj in target_objects:
        anim_data = getattr(obj, "animation_data", None)
        if not anim_data:
            continue

        # 1. Active Action
        if getattr(anim_data, "action", None):
            act = anim_data.action
            act_name = getattr(act, "name", "")
            if act_name and act_name not in discovered_actions:
                discovered_actions[act_name] = _extract_action_info(act, obj)

        # 2. NLA Tracks
        nla_tracks = getattr(anim_data, "nla_tracks", None)
        if nla_tracks:
            for track in nla_tracks:
                for strip in getattr(track, "strips", []):
                    strip_act = getattr(strip, "action", None)
                    if strip_act:
                        s_name = getattr(strip_act, "name", "")
                        if s_name and s_name not in discovered_actions:
                            discovered_actions[s_name] = _extract_action_info(strip_act, obj)

    return list(discovered_actions.values())


def _extract_action_info(action: Any, bound_object: Any) -> dict[str, Any]:
    """Extracts frame range, semantic tags, and GUID for an action."""
    raw_name = getattr(action, "name", "Action")
    sanitized = (
        AnimationRigSanitizer.sanitize_action_name(raw_name)
        if hasattr(AnimationRigSanitizer, "sanitize_action_name")
        else raw_name
    )

    frame_range = getattr(action, "frame_range", (0.0, 100.0))
    start_frame = int(round(frame_range[0]))
    end_frame = int(round(frame_range[1]))
    length = max(1, end_frame - start_frame)

    category = getattr(action, "get", lambda *_: "GENERIC")("_omnimesh_category", "GENERIC")
    guid = getattr(action, "get", lambda *_: "")("_omnimesh_guid", "")
    if not guid:
        # Deterministic UUID based on action name
        guid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"omnimesh.anim.{sanitized}"))
        try:
            action["_omnimesh_guid"] = guid
        except Exception as exc:
            logger.debug("Could not cache _omnimesh_guid on action: %s", exc)

    return {
        "name": raw_name,
        "sanitized_name": sanitized,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "length": length,
        "category": category,
        "guid": guid,
        "bound_object": getattr(bound_object, "name", ""),
    }


def tag_action_category(action_name: str, category: str, custom_guid: Optional[str] = None) -> bool:
    """Assigns semantic category and optional custom GUID to a Blender action."""
    if not bpy or not hasattr(bpy.data, "actions"):
        return False

    act = bpy.data.actions.get(action_name)
    if not act:
        return False

    cat_upper = str(category).strip().upper() or "GENERIC"
    act["_omnimesh_category"] = cat_upper

    if custom_guid:
        act["_omnimesh_guid"] = str(custom_guid).strip()
    elif "_omnimesh_guid" not in act:
        sanitized = (
            AnimationRigSanitizer.sanitize_action_name(action_name)
            if hasattr(AnimationRigSanitizer, "sanitize_action_name")
            else action_name
        )
        act["_omnimesh_guid"] = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"omnimesh.anim.{sanitized}"))

    return True


def build_msfs_animation_xml_block(actions: list[dict[str, Any]]) -> tuple[str, str]:
    """
    Constructs clean, valid MSFS ModelInfo.xml <Animation> and <PartInfo> XML strings.
    Returns: (animations_xml, part_info_xml)
    """
    anim_lines = ["  <Animation>"]
    part_lines = []

    for item in actions:
        name = item.get("sanitized_name", item.get("name", "Action"))
        guid = item.get("guid", str(uuid.uuid4()))
        length = item.get("length", 100)
        category = item.get("category", "GENERIC")
        simvar = SIMVAR_MAPPINGS.get(category, "TIME OF DAY")

        anim_lines.append(
            f'    <Animation name="{name}" guid="{guid}" length="{length}" type="Sim" typeParam="AutoPlay" />'
        )

        part_lines.append("  <PartInfo>")
        part_lines.append(f"    <Name>{name}</Name>")
        part_lines.append(f"    <AnimLength>{length}</AnimLength>")
        part_lines.append("    <Animation>")
        part_lines.append("      <Parameter>")
        part_lines.append("        <Sim>")
        part_lines.append(f"          <Variable>{simvar}</Variable>")
        part_lines.append("        </Sim>")
        part_lines.append("      </Parameter>")
        part_lines.append("    </Animation>")
        part_lines.append("  </PartInfo>")

    anim_lines.append("  </Animation>")
    return "\n".join(anim_lines), "\n".join(part_lines)
