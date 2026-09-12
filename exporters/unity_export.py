"""
Unity 6 Exporter for LOD Meshes and Collision Hulls.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

import re

try:
    import bpy
except ImportError:
    bpy = None


try:
    from .engine_export import AssetMeshResolver
except (ImportError, ValueError):
    try:
        from exporters.engine_export import AssetMeshResolver
    except (ImportError, ValueError):
        AssetMeshResolver = None  # type: ignore


class UnityExporter:
    @classmethod
    def export_asset(cls, context: Any, export_dir: str, asset_name: str) -> tuple[bool, str]:
        if not bpy or not context:
            return False, "Blender bpy not available."
        clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(asset_name)).strip() or "SM_Asset"

        try:
            os.makedirs(export_dir, exist_ok=True)
        except OSError as exc:
            return False, f"Failed creating export directory '{export_dir}': {exc}"

        payload = AssetMeshResolver.resolve_payload(context, clean_name) if AssetMeshResolver else None
        if not payload or not payload.lod_tiers:
            return False, f"No generated LOD objects found for '{asset_name}'"

        if hasattr(bpy.ops.object, "mode_set") and getattr(context, "mode", "") != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception as exc:
                logger.debug("Mode set to OBJECT skipped: %s", exc)

        export_objects: list[Any] = []
        for tier_idx in sorted(payload.lod_tiers.keys()):
            for obj in payload.lod_tiers[tier_idx]:
                if obj not in export_objects:
                    export_objects.append(obj)

        if not export_objects:
            return False, f"No generated LOD objects found for '{asset_name}'"

        collider_objects = list(payload.collider_objects)
        orig_collider_names: dict[Any, str] = {}
        fbx_path = os.path.join(export_dir, f"{clean_name}.fbx")

        try:
            # Normalize collider names for Unity C# postprocessor regex (_Collider\d*|UCX_)
            for idx, c_obj in enumerate(collider_objects, start=1):
                if hasattr(c_obj, "name"):
                    orig_collider_names[c_obj] = c_obj.name
                    if not (c_obj.name.startswith("UCX_") or "_Collider" in c_obj.name):
                        c_obj.name = f"{clean_name}_Collider_{idx:02d}"

            # Unhide all objects in view layer
            for obj in export_objects + collider_objects:
                try:
                    obj.hide_set(False, view_layer=context.view_layer)
                    obj.hide_viewport = False
                except (RuntimeError, AttributeError) as exc:
                    logger.debug("Could not unhide object %s in view layer: %s", getattr(obj, "name", "unknown"), exc)

            bpy.ops.object.select_all(action="DESELECT")
            for obj in export_objects:
                obj.select_set(True)
            for c_obj in collider_objects:
                c_obj.select_set(True)

            context.view_layer.objects.active = export_objects[0]

            bpy.ops.export_scene.fbx(
                filepath=fbx_path,
                use_selection=True,
                apply_unit_scale=True,
                apply_scale_options="FBX_SCALE_ALL",
                bake_space_transform=True,
                object_types={"MESH", "ARMATURE", "EMPTY"},
                mesh_smooth_type="FACE",
                primary_bone_axis="Y",
                secondary_bone_axis="X",
                armature_nodetype="NULL",
            )
            return True, f"Unity FBX package exported to: {fbx_path}"
        except Exception as e:
            return False, f"Failed to export Unity FBX: {str(e)}"
        finally:
            for c_obj, orig_name in orig_collider_names.items():
                try:
                    c_obj.name = orig_name
                except Exception as exc:
                    logger.debug("Could not restore collider name for %s: %s", getattr(c_obj, "name", "obj"), exc)
