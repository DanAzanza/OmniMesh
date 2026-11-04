"""
OmniMesh Multi-Engine Animation & Action Tagging Manager.
Discovers, sanitizes, and categorizes Blender Actions and NLA tracks on active assets,
ensuring clean cross-engine export (glTF/FBX) and deterministic MSFS ModelInfo XML
<Animation> and <PartInfo> generation without broken GUID references.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional
import uuid

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from bpy.types import Action, BlendData, Object
else:
    try:
        from bpy.types import Action, BlendData, Object
    except ImportError:
        Action = object
        BlendData = object
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


def scan_asset_animations(
    blend_data: BlendData,
    asset_name: str,
) -> list[dict[str, Any]]:
    """
    Scans armatures and animated meshes associated with the given asset in blend_data,
    returning detailed metadata for all actions and NLA tracks.
    """
    if blend_data is None:
        raise ValueError("blend_data must not be None when scanning asset animations.")

    clean_asset = str(asset_name).strip() or "Asset"
    discovered_actions: dict[str, dict[str, Any]] = {}

    target_objects: list[Object] = []
    root_col = blend_data.collections.get(clean_asset)
    if root_col is not None and root_col.all_objects:
        target_objects = list(root_col.all_objects)

    if not target_objects:
        target_objects = [
            obj for obj in blend_data.objects if obj.name == clean_asset or obj.name.startswith(f"{clean_asset}_")
        ]

    for obj in target_objects:
        anim_data = obj.animation_data
        if not anim_data:
            continue

        # 1. Active Action
        act = anim_data.action
        if act is not None and act.name and act.name not in discovered_actions:
            discovered_actions[act.name] = _extract_action_info(act, obj)

        # 2. NLA Tracks
        for track in anim_data.nla_tracks:
            for strip in track.strips:
                strip_act = strip.action
                if strip_act is not None and strip_act.name and strip_act.name not in discovered_actions:
                    discovered_actions[strip_act.name] = _extract_action_info(strip_act, obj)

    return list(discovered_actions.values())


def _extract_action_info(action: Action | None, bound_object: Object | None) -> dict[str, Any]:
    """Extracts frame range, semantic tags, and GUID for an action."""
    if not action:
        return {
            "name": "Action",
            "sanitized_name": "Action",
            "start_frame": 0,
            "end_frame": 100,
            "length": 100,
            "category": "GENERIC",
            "guid": "",
            "bound_object": bound_object.name if bound_object else "",
        }
    raw_name = action.name or "Action"
    sanitized = AnimationRigSanitizer.sanitize_action_name(raw_name)

    frame_range = action.frame_range
    start_frame = int(round(frame_range[0]))
    end_frame = int(round(frame_range[1]))
    length = max(1, end_frame - start_frame)

    category = str(action.get("_omnimesh_category", "GENERIC"))
    guid = str(action.get("_omnimesh_guid", ""))
    if not guid:
        guid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"omnimesh.anim.{sanitized}"))
        try:
            action["_omnimesh_guid"] = guid
        except (TypeError, ValueError, AttributeError) as exc:
            logger.debug("Could not cache _omnimesh_guid on action: %s", exc)

    return {
        "name": raw_name,
        "sanitized_name": sanitized,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "length": length,
        "category": category,
        "guid": guid,
        "bound_object": bound_object.name if bound_object else "",
    }


def tag_action_category(
    action_name: str,
    category: str,
    blend_data: BlendData,
    custom_guid: Optional[str] = None,
) -> bool:
    """Assigns semantic category and optional custom GUID to a Blender action."""
    if blend_data is None:
        raise ValueError("blend_data must not be None when tagging actions.")

    act: Action | None = blend_data.actions.get(action_name)
    if act is None:
        return False

    cat_upper = str(category).strip().upper() or "GENERIC"
    act["_omnimesh_category"] = cat_upper

    if custom_guid:
        act["_omnimesh_guid"] = str(custom_guid).strip()
    elif not act.get("_omnimesh_guid"):
        sanitized = AnimationRigSanitizer.sanitize_action_name(action_name)
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
