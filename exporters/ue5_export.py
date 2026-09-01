"""
Unreal Engine 5 (UE5) Exporter for Static & Skeletal LOD Meshes.
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


class UE5Exporter:
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

        # Check if this is a skeletal mesh asset
        armature_obj = None
        for obj in export_objects:
            if obj.parent and obj.parent.type == "ARMATURE":
                armature_obj = obj.parent
                break
            for mod in getattr(obj, "modifiers", []):
                if mod.type == "ARMATURE" and mod.object:
                    armature_obj = mod.object
                    break

        # Unhide all objects in the view layer before selection
        for obj in export_objects:
            try:
                obj.hide_set(False, view_layer=context.view_layer)
                obj.hide_viewport = False
            except (RuntimeError, AttributeError) as exc:
                logger.debug("Could not unhide object %s in view layer: %s", getattr(obj, "name", "unknown"), exc)

        if armature_obj:
            try:
                armature_obj.hide_set(False, view_layer=context.view_layer)
                armature_obj.hide_viewport = False
            except (RuntimeError, AttributeError) as exc:
                logger.debug(
                    "Could not unhide armature %s in view layer: %s", getattr(armature_obj, "name", "unknown"), exc
                )

        bpy.ops.object.select_all(action="DESELECT")

        if armature_obj:
            # Skeletal Mesh export branch: select Armature and all child LOD meshes
            armature_obj.select_set(True)
            for obj in export_objects:
                obj.select_set(True)
            context.view_layer.objects.active = armature_obj
        else:
            # Static Mesh export branch: create or configure LODGroup parent empty
            empty_name = f"LODGroup_{asset_name}"
            lod_group_empty = bpy.data.objects.get(empty_name)
            if not lod_group_empty:
                lod_group_empty = bpy.data.objects.new(empty_name, None)
                lod_group_empty.empty_display_type = "PLAIN_AXES"
                context.scene.collection.objects.link(lod_group_empty)
            else:
                if lod_group_empty.name not in context.scene.collection.objects:
                    try:
                        context.scene.collection.objects.link(lod_group_empty)
                    except RuntimeError as exc:
                        logger.debug("LODGroup empty already linked: %s", exc)

            try:
                lod_group_empty.hide_set(False, view_layer=context.view_layer)
                lod_group_empty.hide_viewport = False
            except (RuntimeError, AttributeError) as exc:
                logger.debug("Could not unhide lod_group_empty in view layer: %s", exc)

            lod_group_empty["fbx_type"] = "LodGroup"

            for obj in export_objects:
                if obj.parent != lod_group_empty:
                    obj.parent = lod_group_empty

            lod_group_empty.select_set(True)
            for obj in export_objects:
                obj.select_set(True)
            context.view_layer.objects.active = lod_group_empty

        fbx_path = os.path.join(export_dir, f"{asset_name}.fbx")

        try:
            bpy.ops.export_scene.fbx(
                filepath=fbx_path,
                use_selection=True,
                apply_unit_scale=True,
                apply_scale_options="FBX_SCALE_ALL",
                bake_space_transform=True,
                object_types={"ARMATURE", "MESH", "EMPTY"} if armature_obj else {"MESH", "EMPTY"},
                mesh_smooth_type="FACE",
                add_leaf_bones=False if armature_obj else True,
                primary_bone_axis="Y",
                secondary_bone_axis="X",
                armature_nodetype="NULL",
            )
            return True, f"UE5 FBX package exported to: {fbx_path}"
        except Exception as e:
            return False, f"Failed to export UE5 FBX: {str(e)}"
