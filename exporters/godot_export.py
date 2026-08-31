"""
Godot 4.x glTF Exporter.
"""

from __future__ import annotations

import os
from typing import Any

try:
    import bpy
except ImportError:
    bpy = None


class GodotExporter:
    @classmethod
    def export_asset(cls, context: Any, export_dir: str, asset_name: str) -> tuple[bool, str]:
        if not bpy:
            return False, "Blender bpy not available."
        props = context.scene.lod_tool
        os.makedirs(export_dir, exist_ok=True)

        bpy.ops.object.select_all(action="DESELECT")
        first_obj = None

        for i, tier in enumerate(props.lods):
            if tier.generated_obj:
                obj = tier.generated_obj
                obj.select_set(True)
                if not first_obj:
                    first_obj = obj

                dist_begin = 0.0 if i == 0 else props.lods[i - 1].distance_m
                dist_end = tier.distance_m
                obj["visibility_range_begin"] = dist_begin
                obj["visibility_range_end"] = dist_end

        if not first_obj:
            return False, "No generated LOD objects found to export."

        context.view_layer.objects.active = first_obj

        gltf_path = os.path.join(export_dir, f"{asset_name}.gltf")
        try:
            bpy.ops.export_scene.gltf(
                filepath=gltf_path, use_selection=True, export_format="GLTF_SEPARATE", export_extras=True
            )
            return True, f"Godot 4 glTF exported to: {gltf_path}"
        except Exception as e:
            return False, f"Failed to export Godot glTF: {str(e)}"
