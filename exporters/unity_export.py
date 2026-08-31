"""
Unity 6 Exporter for LOD Meshes.
"""

from __future__ import annotations

import os
from typing import Any

try:
    import bpy
except ImportError:
    bpy = None


class UnityExporter:
    @classmethod
    def export_asset(cls, context: Any, export_dir: str, asset_name: str) -> tuple[bool, str]:
        if not bpy:
            return False, "Blender bpy not available."
        props = context.scene.lod_tool
        os.makedirs(export_dir, exist_ok=True)

        coll = bpy.data.collections.get(f"{props.export_base_name}_LODs")
        if not coll or len(coll.objects) == 0:
            return False, f"No generated LOD collection found for '{props.export_base_name}'"

        bpy.ops.object.select_all(action="DESELECT")
        for obj in coll.objects:
            obj.select_set(True)

        context.view_layer.objects.active = coll.objects[0]

        fbx_path = os.path.join(export_dir, f"{asset_name}.fbx")

        try:
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
