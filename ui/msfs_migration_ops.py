"""
Operator for non-destructive migration of legacy MSFS / Asobo x0_..x6_ outliner hierarchies
into OmniMesh Variante A standard ({AssetName}_LOD0..N, {AssetName}_Config, {AssetName}_Helpers).
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bpy
    from bpy.types import Operator
except ImportError:
    bpy = None
    Operator = object

try:
    from ..core.hierarchy import get_or_create_engine_import_collection
    from .utils import safe_report
except (ImportError, ValueError):
    from core.hierarchy import get_or_create_engine_import_collection
    from ui.utils import safe_report


class OMNIMESH_OT_convert_asobo_hierarchy(Operator):
    """Convert legacy Asobo x0_..x6_ collection hierarchy into OmniMesh Variante A ({AssetName}_LOD0..N)."""

    bl_idname = "omnimesh.convert_asobo_hierarchy"
    bl_label = "Convert Asobo x0..x6 Hierarchy"
    bl_description = (
        "Reorganizes legacy MSFS/Asobo x0_..x6_ collections into OmniMesh Variante A "
        "standard ({AssetName}_LOD0..N) while preserving rigs, armatures, and helpers"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        if not bpy or not context:
            return False
        collections = getattr(getattr(bpy, "data", None), "collections", None)
        if not collections:
            return False
        return any(re.match(r"^x[0-6]_", getattr(c, "name", ""), re.IGNORECASE) for c in collections)

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}

        scene = getattr(context, "scene", None)
        if not scene:
            return {"CANCELLED"}

        pattern = re.compile(r"^x([0-6])_(.*)$", re.IGNORECASE)
        asobo_colls: list[tuple[int, str, Any]] = []

        for coll in bpy.data.collections:
            match = pattern.match(coll.name)
            if match:
                tier_idx = int(match.group(1))
                rest = match.group(2).strip()
                asobo_colls.append((tier_idx, rest, coll))

        if not asobo_colls:
            safe_report(self, {"WARNING"}, "No legacy Asobo x0_..x6_ collections found.")
            return {"CANCELLED"}

        x0_entries = [rest for (tier, rest, coll) in asobo_colls if tier == 0]
        if x0_entries:
            asset_name = x0_entries[0]
        else:
            asset_name = asobo_colls[0][1]

        asset_name = re.sub(r'[\s<>:"/\\|?*]+', "_", asset_name).strip("_")
        if not asset_name:
            asset_name = "MSFS_Asset"

        get_or_create_engine_import_collection(context, asset_name, "ROOT")
        get_or_create_engine_import_collection(context, asset_name, "CONFIG")
        helpers_col = get_or_create_engine_import_collection(context, asset_name, "HELPERS")

        migrated_objects_count = 0

        for tier_idx, _sub_name, old_col in sorted(asobo_colls, key=lambda x: x[0]):
            target_lod_role = f"LOD{tier_idx}"
            target_lod_col = get_or_create_engine_import_collection(context, asset_name, target_lod_role)

            for obj in list(getattr(old_col, "objects", [])):
                obj_name_upper = getattr(obj, "name", "").upper()

                is_helper = (
                    obj.type == "EMPTY"
                    and any(
                        obj_name_upper.startswith(pfx)
                        for pfx in ("ATTACH_POINT", "ATTACH_FX", "ROOT_ATTACH", "SOCKET", "EYE", "COLLISION")
                    )
                ) or obj.type in ("CAMERA", "LIGHT")

                dest_col = helpers_col if is_helper else target_lod_col

                if dest_col:
                    dest_objs = getattr(dest_col, "objects", None)
                    if hasattr(dest_objs, "link"):
                        try:
                            if obj.name not in dest_objs:
                                dest_objs.link(obj)
                        except (RuntimeError, TypeError):
                            pass
                    elif isinstance(dest_objs, list) and obj not in dest_objs:
                        dest_objs.append(obj)

                # Unlink from old collection
                old_objs = getattr(old_col, "objects", None)
                if hasattr(old_objs, "unlink"):
                    try:
                        old_objs.unlink(obj)
                        migrated_objects_count += 1
                    except RuntimeError:
                        pass
                elif isinstance(old_objs, list) and obj in old_objs:
                    old_objs.remove(obj)
                    migrated_objects_count += 1

        cleaned_colls = 0
        for _tier, _sub, old_col in asobo_colls:
            if len(getattr(old_col, "objects", [])) == 0 and len(getattr(old_col, "children", [])) == 0:
                try:
                    bpy.data.collections.remove(old_col)
                    cleaned_colls += 1
                except Exception as exc:
                    logger.debug("Could not remove old collection %s: %s", getattr(old_col, "name", ""), exc)

        safe_report(
            self,
            {"INFO"},
            f"Migrated {migrated_objects_count} object(s) into '{asset_name}' Variante A ({cleaned_colls} collections cleaned).",
        )
        return {"FINISHED"}


MIGRATION_OPERATOR_CLASSES = (OMNIMESH_OT_convert_asobo_hierarchy,)


def register() -> None:
    if not bpy:
        return
    for cls in MIGRATION_OPERATOR_CLASSES:
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            logger.debug("Could not register %s: %s", getattr(cls, "__name__", "cls"), exc)


def unregister() -> None:
    if not bpy:
        return
    for cls in reversed(MIGRATION_OPERATOR_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:
            logger.debug("Could not unregister %s: %s", getattr(cls, "__name__", "cls"), exc)
