"""
Godot 4.x glTF Exporter.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

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
        os.makedirs(export_dir, exist_ok=True)

        coll = bpy.data.collections.get(f"{asset_name}_LODs") or (
            bpy.data.collections.get(f"{props.export_base_name}_LODs") if props else None
        )

        all_objs: list[Any] = []
        if coll and len(coll.objects) > 0:
            all_objs = list(coll.objects)
        elif props and len(props.lods) > 0:
            all_objs = [tier.generated_obj for tier in props.lods if tier.generated_obj]

        if not all_objs:
            return False, "No generated LOD objects found to export."

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
