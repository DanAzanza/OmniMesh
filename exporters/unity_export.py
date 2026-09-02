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


class UnityExporter:
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

        export_objects: list[Any] = []
        base_search = clean_name.split("_LOD")[0]

        # 1. LOD0 Root Collection
        root_c = bpy.data.collections.get(base_search) or (
            bpy.data.collections.get(props.export_base_name) if props else None
        )
        if root_c:
            export_objects.extend(
                [obj for obj in root_c.objects if obj.type in {"MESH", "EMPTY"} and not obj.get("_is_collider", False)]
            )

        # 2. Sibling LOD Collections (LOD1..k)
        if props and len(props.lods) > 0:
            for i in range(1, len(props.lods)):
                s_c = bpy.data.collections.get(f"{base_search}_LOD{i}")
                if s_c:
                    export_objects.extend(
                        [
                            obj
                            for obj in s_c.objects
                            if obj.type in {"MESH", "EMPTY"} and not obj.get("_is_collider", False)
                        ]
                    )

        # 3. Impostor Collection
        imp_c = bpy.data.collections.get(f"{base_search}_LOD_Impostor")
        if imp_c:
            export_objects.extend(list(imp_c.objects))

        # 4. Fallback to direct tier references
        if not export_objects and props and len(props.lods) > 0:
            export_objects = [tier.generated_obj for tier in props.lods if tier.generated_obj]

        if not export_objects:
            return False, f"No generated LOD objects found for '{asset_name}'"

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
