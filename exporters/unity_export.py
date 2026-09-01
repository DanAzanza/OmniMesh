"""
Unity 6 Exporter for LOD Meshes.
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


class UnityExporter:
    @classmethod
    def export_asset(cls, context: Any, export_dir: str, asset_name: str) -> tuple[bool, str]:
        if not bpy or not context:
            return False, "Blender bpy not available."
        props = getattr(context.scene, "lod_tool", None)
        os.makedirs(export_dir, exist_ok=True)

        coll = bpy.data.collections.get(f"{asset_name}_LODs") or (
            bpy.data.collections.get(f"{props.export_base_name}_LODs") if props else None
        )

        export_objects: list[Any] = []
        if coll and len(coll.objects) > 0:
            export_objects = [obj for obj in coll.objects]
        elif props and len(props.lods) > 0:
            export_objects = [tier.generated_obj for tier in props.lods if tier.generated_obj]

        if not export_objects:
            return False, f"No generated LOD objects found for '{asset_name}'"

        # Unhide all objects in view layer
        for obj in export_objects:
            try:
                obj.hide_set(False, view_layer=context.view_layer)
                obj.hide_viewport = False
            except (RuntimeError, AttributeError) as exc:
                logger.debug("Could not unhide object %s in view layer: %s", getattr(obj, "name", "unknown"), exc)

        bpy.ops.object.select_all(action="DESELECT")
        for obj in export_objects:
            obj.select_set(True)

        context.view_layer.objects.active = export_objects[0]

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
