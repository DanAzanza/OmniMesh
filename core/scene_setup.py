"""
OmniMesh Scene Setup & Asset Hierarchy Module.
Architected for Blender 4.2+ LTS & Blender 5.2 LTS.
Features:
- Game engine standard scene settings (Metric 1.0, 60 FPS, optimized clipping, stats, cavity shading).
- Standardized nested collection hierarchies ({AssetName} -> _LOD0, _Colliders, _Helpers, _Config).
- Blender 4.x/5.x native Outliner collection color tags.
- Safe object routing: MESH to LOD0, ARMATURE to Root (SharedRigAnchor), Empties to Helpers/LOD0.
- Defensive linking hygiene and headless CI execution safety.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import bpy
except ImportError:
    bpy = None

# Native Outliner Collection Color Tags (Blender 4.0+)
# COLOR_01: Red, COLOR_02: Orange, COLOR_03: Yellow, COLOR_04: Green,
# COLOR_05: Blue, COLOR_06: Violet/Purple, COLOR_07: Pink, COLOR_08: Brown/Neutral
COLLECTION_COLOR_TAGS: dict[str, str] = {
    "ROOT": "COLOR_08",
    "LOD0": "COLOR_04",
    "LOD": "COLOR_05",
    "COLLIDERS": "COLOR_02",
    "HELPERS": "COLOR_03",
    "CONFIG": "COLOR_06",
}


def sanitize_asset_name(raw_name: str) -> str:
    """
    Cleanses an object or collection name into a valid, canonical OmniMesh asset identifier.
    Strips trailing Blender duplicate suffixes (e.g. '.001'), known technical/LOD suffixes,
    and replaces invalid filesystem/XML characters with underscores.
    """
    if not raw_name or not str(raw_name).strip():
        return "Asset"

    name = str(raw_name).strip()

    # 1. Strip Blender duplicate numeric suffix (.001, .002, etc.)
    name = re.sub(r"\.\d{3,}$", "", name)

    # 2. Strip known OmniMesh technical and LOD suffixes
    for n in range(0, 11):
        if name.endswith(f"_LOD{n}"):
            name = name[: -len(f"_LOD{n}")]
            break

    for sfx in (
        "_Colliders",
        "_Collider",
        "_Helpers",
        "_Helper",
        "_Config",
        "_Spatial",
        "_Lights",
        "_Cameras",
        "_Attachments",
        "_Interactions",
        "_Impostor",
        "_Chunks",
        "_HLOD",
        "_Mesh",
    ):
        if name.endswith(sfx):
            name = name[: -len(sfx)]
            break

    # 3. Replace non-alphanumeric characters (except underscores and hyphens)
    cleaned = re.sub(r"[^\w\-]", "_", name)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")

    return cleaned or "Asset"


def configure_game_scene_settings(
    scene: Any,
    *,
    unit_scale: float = 1.0,
    length_unit: str = "METERS",
    fps: int = 60,
    clip_start: float = 0.05,
    clip_end: float = 1000.0,
    enable_stats: bool = True,
    enable_cavity: bool = True,
    enable_backface_culling: bool = True,
    context: Any = None,
) -> dict[str, Any]:
    """
    Configures Blender scene and viewport parameters to game engine development standards.
    Safely executes in headless CI / CLI batch environments where no window manager exists.
    """
    result: dict[str, Any] = {
        "scene_configured": False,
        "viewports_updated": 0,
    }

    if not scene:
        return result

    # 1. Metric Unit Standards
    if hasattr(scene, "unit_settings"):
        try:
            scene.unit_settings.system = "METRIC"
            scene.unit_settings.scale_length = float(unit_scale)
            scene.unit_settings.length_unit = length_unit
        except (AttributeError, TypeError, ValueError) as exc:
            logger.debug("Could not set unit_settings: %s", exc)

    # 2. Game Frame Rate Standards (fps + fps_base)
    if hasattr(scene, "render"):
        try:
            scene.render.fps = int(fps)
            scene.render.fps_base = 1.0
        except (AttributeError, TypeError, ValueError) as exc:
            logger.debug("Could not set render.fps: %s", exc)

    result["scene_configured"] = True

    # 3. Viewport Shading, Clipping & Overlay Inspections (Safely traversed)
    ctx = context or (getattr(bpy, "context", None) if bpy else None)
    wm = getattr(ctx, "window_manager", None) if ctx else None
    viewports_count = 0

    if wm and hasattr(wm, "windows"):
        try:
            for window in getattr(wm, "windows", []):
                screen = getattr(window, "screen", None)
                if not screen or not hasattr(screen, "areas"):
                    continue
                for area in getattr(screen, "areas", []):
                    if getattr(area, "type", "") == "VIEW_3D":
                        for space in getattr(area, "spaces", []):
                            if getattr(space, "type", "") == "VIEW_3D":
                                _apply_viewport_space_settings(
                                    space,
                                    clip_start=clip_start,
                                    clip_end=clip_end,
                                    enable_stats=enable_stats,
                                    enable_cavity=enable_cavity,
                                    enable_backface_culling=enable_backface_culling,
                                )
                                viewports_count += 1
        except Exception as exc:
            logger.debug("Viewport space traversal skipped or partially failed: %s", exc)

    result["viewports_updated"] = viewports_count
    return result


def _apply_viewport_space_settings(
    space: Any,
    *,
    clip_start: float,
    clip_end: float,
    enable_stats: bool,
    enable_cavity: bool,
    enable_backface_culling: bool,
) -> None:
    """Applies clipping and overlay/shading options to a single SpaceView3D instance."""
    if hasattr(space, "clip_start"):
        space.clip_start = float(clip_start)
    if hasattr(space, "clip_end"):
        space.clip_end = float(clip_end)

    overlay = getattr(space, "overlay", None)
    if overlay and hasattr(overlay, "show_stats"):
        overlay.show_stats = bool(enable_stats)

    shading = getattr(space, "shading", None)
    if shading:
        if hasattr(shading, "show_cavity"):
            shading.show_cavity = bool(enable_cavity)
        if hasattr(shading, "cavity_type"):
            shading.cavity_type = "BOTH"
        if hasattr(shading, "show_backface_culling"):
            shading.show_backface_culling = bool(enable_backface_culling)


def setup_asset_collections(
    context: Any,
    asset_name: str,
    *,
    create_lod0: bool = True,
    create_colliders: bool = True,
    create_helpers: bool = True,
    create_config: bool = False,
    apply_color_tags: bool = True,
    bpy_module: Any = None,
) -> dict[str, Any]:
    """
    Creates or retrieves the standardized OmniMesh asset collection hierarchy:
    Scene Collection
       └── {AssetName} (Root, COLOR_08)
            ├── {AssetName}_LOD0 (COLOR_04)
            ├── {AssetName}_Colliders (COLOR_02)
            ├── {AssetName}_Helpers (COLOR_03)
            └── {AssetName}_Config (COLOR_06) [Optional]
    """
    _bpy = bpy_module or bpy
    if not _bpy or not context:
        return {}

    scene = getattr(context, "scene", None)
    if not scene or not hasattr(scene, "collection"):
        return {}

    clean_asset = sanitize_asset_name(asset_name)
    collections: dict[str, Any] = {}

    # 1. Root Collection {AssetName}
    root_col = _bpy.data.collections.get(clean_asset)
    if not root_col:
        root_col = _bpy.data.collections.new(clean_asset)
        scene.collection.children.link(root_col)
    elif root_col.name not in scene.collection.children:
        try:
            scene.collection.children.link(root_col)
        except RuntimeError:
            pass

    root_col["_omnimesh_role"] = "MODEL_ROOT"
    if apply_color_tags and hasattr(root_col, "color_tag"):
        root_col.color_tag = COLLECTION_COLOR_TAGS.get("ROOT", "COLOR_08")

    collections["root"] = root_col

    # Helper function for nested sub-collections
    def _ensure_sub_collection(role_key: str, sub_name: str) -> Any:
        sub_col = _bpy.data.collections.get(sub_name)
        if not sub_col:
            sub_col = _bpy.data.collections.new(sub_name)
            root_col.children.link(sub_col)
        else:
            if sub_col.name not in root_col.children:
                try:
                    root_col.children.link(sub_col)
                except RuntimeError:
                    pass
            # Unlink from scene.collection if misplaced there directly
            if hasattr(scene.collection, "children") and sub_col.name in scene.collection.children:
                try:
                    scene.collection.children.unlink(sub_col)
                except RuntimeError:
                    pass

        sub_col["_omnimesh_role"] = role_key
        if apply_color_tags and hasattr(sub_col, "color_tag"):
            sub_col.color_tag = COLLECTION_COLOR_TAGS.get(role_key, "NONE")
        return sub_col

    # 2. LOD0 Collection
    if create_lod0:
        collections["lod0"] = _ensure_sub_collection("LOD0", f"{clean_asset}_LOD0")

    # 3. Colliders Collection
    if create_colliders:
        col_col = _ensure_sub_collection("COLLIDERS", f"{clean_asset}_Colliders")
        collections["colliders"] = col_col

    # 4. Helpers Collection
    if create_helpers:
        collections["helpers"] = _ensure_sub_collection("HELPERS", f"{clean_asset}_Helpers")

    # 5. Config Collection (Optional)
    if create_config:
        collections["config"] = _ensure_sub_collection("CONFIG", f"{clean_asset}_Config")

    return collections


def assign_objects_to_asset_hierarchy(
    objects: list[Any],
    collections_map: dict[str, Any],
    scene: Any = None,
    *,
    unlink_from_others: bool = True,
) -> dict[str, Any]:
    """
    Classifies selected objects by datablock type and links them to their appropriate
    hierarchy collection:
    - MESH -> _LOD0
    - ARMATURE -> {AssetName} Root (Preserves SharedRigAnchor across all LOD tiers)
    - LIGHT / CAMERA -> _Config (if present) or skipped
    - EMPTY -> _LOD0 (if socket/attach point), otherwise _Helpers
    - CURVE / FONT / SURFACE -> Skipped

    Enforces linking hygiene: links to target collection BEFORE unlinking from previous
    collections to prevent zero-user datablock orphan deletion.
    """
    summary: dict[str, Any] = {
        "moved_to_lod0": [],
        "moved_to_root": [],
        "moved_to_helpers": [],
        "moved_to_config": [],
        "skipped_library": [],
        "skipped_unsupported": [],
    }

    if not objects or not collections_map:
        return summary

    root_col = collections_map.get("root")
    lod0_col = collections_map.get("lod0")
    helpers_col = collections_map.get("helpers")
    config_col = collections_map.get("config")

    for obj in objects:
        if not obj:
            continue

        obj_name = getattr(obj, "name", "Unnamed")

        # 1. Library-linked datablock guard (cannot modify external library membership)
        if getattr(obj, "library", None) is not None:
            summary["skipped_library"].append(obj_name)
            continue

        obj_type = getattr(obj, "type", "")
        target_col: Optional[Any] = None
        target_category = ""

        if obj_type == "MESH":
            if lod0_col:
                target_col = lod0_col
                target_category = "moved_to_lod0"
            else:
                target_col = root_col
                target_category = "moved_to_root"

        elif obj_type == "ARMATURE":
            # SharedRigAnchor: Master Armatures must stay at the Root collection
            target_col = root_col
            target_category = "moved_to_root"

        elif obj_type in ("LIGHT", "CAMERA"):
            if config_col:
                target_col = config_col
                target_category = "moved_to_config"
            else:
                summary["skipped_unsupported"].append(obj_name)
                continue

        elif obj_type == "EMPTY":
            is_socket = obj_name.startswith("SOCKET_") or obj_name.startswith("ATTACH_POINT_")
            if is_socket and lod0_col:
                target_col = lod0_col
                target_category = "moved_to_lod0"
            elif helpers_col:
                target_col = helpers_col
                target_category = "moved_to_helpers"
            else:
                target_col = root_col
                target_category = "moved_to_root"

        else:
            # Unsupported geometry types (CURVE, FONT, SURFACE, LATTICE, etc.)
            summary["skipped_unsupported"].append(obj_name)
            continue

        if not target_col:
            continue

        # 2. Defensive link-first, unlink-after pattern
        if hasattr(target_col, "objects") and obj_name not in target_col.objects:
            try:
                target_col.objects.link(obj)
            except RuntimeError as exc:
                logger.debug("Could not link %s to %s: %s", obj_name, getattr(target_col, "name", ""), exc)
                continue

        if unlink_from_others:
            if hasattr(obj, "users_collection"):
                for col in list(getattr(obj, "users_collection", [])):
                    if col != target_col and hasattr(col, "objects") and obj_name in col.objects:
                        try:
                            col.objects.unlink(obj)
                        except (RuntimeError, ReferenceError):
                            pass

            if scene and hasattr(scene, "collection") and scene.collection != target_col:
                if hasattr(scene.collection, "objects") and obj_name in scene.collection.objects:
                    try:
                        scene.collection.objects.unlink(obj)
                    except (RuntimeError, ReferenceError):
                        pass

        if target_category:
            summary[target_category].append(obj_name)

    return summary
