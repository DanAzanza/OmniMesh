"""
Godot 4.x glTF Exporter for LOD Meshes and -convcol Collision Shapes.
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


class GodotExporter:
    @classmethod
    def export_asset(cls, context: Any, export_dir: str, asset_name: str) -> tuple[bool, str]:
        if not bpy or not context:
            return False, "Blender bpy not available."
        props = getattr(context.scene, "lod_tool", None)
        clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(asset_name)).strip() or "SM_Asset"

        try:
            os.makedirs(export_dir, exist_ok=True)
        except OSError as exc:
            return False, f"Failed creating export directory '{export_dir}': {exc}"

        all_objs: list[Any] = []
        base_search = clean_name.split("_LOD")[0]

        # 1. LOD0 Root Collection
        root_c = bpy.data.collections.get(base_search) or (
            bpy.data.collections.get(props.export_base_name) if props else None
        )
        if root_c:
            all_objs.extend(
                [obj for obj in root_c.objects if obj.type in {"MESH", "EMPTY"} and not obj.get("_is_collider", False)]
            )

        # 2. Sibling LOD Collections (LOD1..k)
        if props and len(props.lods) > 0:
            for i in range(1, len(props.lods)):
                s_c = bpy.data.collections.get(f"{base_search}_LOD{i}")
                if s_c:
                    all_objs.extend(
                        [
                            obj
                            for obj in s_c.objects
                            if obj.type in {"MESH", "EMPTY"} and not obj.get("_is_collider", False)
                        ]
                    )

        # 3. Impostor Collection
        imp_c = bpy.data.collections.get(f"{base_search}_LOD_Impostor")
        if imp_c:
            all_objs.extend(list(imp_c.objects))

        # 4. Fallback to direct tier references
        if not all_objs and props and len(props.lods) > 0:
            all_objs = [tier.generated_obj for tier in props.lods if tier.generated_obj]

        if not all_objs:
            return False, "No generated LOD objects found to export."

        # Collect optional collision hull objects
        coll_coll = bpy.data.collections.get(f"{asset_name}_Colliders") or (
            bpy.data.collections.get(f"{props.export_base_name}_Colliders") if props else None
        )
        collider_objects: list[Any] = []
        if coll_coll and len(coll_coll.objects) > 0:
            collider_objects = list(coll_coll.objects)
        else:
            base_search = asset_name.split("_LOD")[0]
            collider_objects = [
                obj
                for obj in bpy.data.objects
                if obj.get("_is_collider", False) or f"{base_search}_Collider_" in obj.name
            ]

        bpy.ops.object.select_all(action="DESELECT")

        for obj in all_objs:
            try:
                obj.hide_set(False, view_layer=context.view_layer)
                obj.hide_viewport = False
            except (RuntimeError, AttributeError) as exc:
                logger.debug("Could not unhide object %s in view layer: %s", getattr(obj, "name", "unknown"), exc)

            tier_idx = 0
            for i in range(10):
                if f"_LOD{i}" in obj.name:
                    tier_idx = i
                    break

            dist_begin = 0.0
            dist_end = 100.0
            if props and len(props.lods) > 0:
                dist_begin = 0.0 if tier_idx == 0 else props.lods[min(tier_idx - 1, len(props.lods) - 1)].distance_m
                dist_end = props.lods[min(tier_idx, len(props.lods) - 1)].distance_m

            obj["visibility_range_begin"] = dist_begin
            obj["visibility_range_end"] = dist_end
            obj.select_set(True)

        # Prepare and select collider objects with -convcol suffix
        orig_collider_names: dict[Any, str] = {}
        for idx, c_obj in enumerate(collider_objects, start=1):
            try:
                c_obj.hide_set(False, view_layer=context.view_layer)
                c_obj.hide_viewport = False
                orig_collider_names[c_obj] = c_obj.name
                if not c_obj.name.endswith("-convcol"):
                    c_obj.name = f"{asset_name}_Collider_{idx:02d}-convcol"
                c_obj.select_set(True)
            except (RuntimeError, AttributeError) as exc:
                logger.debug("Could not prepare collider %s: %s", getattr(c_obj, "name", "unknown"), exc)

        context.view_layer.objects.active = all_objs[0]

        gltf_path = os.path.join(export_dir, f"{asset_name}.gltf")
        try:
            bpy.ops.export_scene.gltf(
                filepath=gltf_path,
                use_selection=True,
                export_format="GLTF_SEPARATE",
                export_extras=True,
                export_apply=True,
            )
            return True, f"Godot 4 glTF exported to: {gltf_path}"
        except Exception as e:
            return False, f"Failed to export Godot glTF: {str(e)}"
        finally:
            # Restore original collider names
            for c_obj, orig_name in orig_collider_names.items():
                try:
                    c_obj.name = orig_name
                except Exception as exc:
                    logger.debug("Restoring collider name failed: %s", exc)
