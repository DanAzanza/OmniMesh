"""
Unreal Engine 5 (UE5) Exporter for Static & Skeletal LOD Meshes and UCX Collision Hulls.
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


class UE5Exporter:
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

        # Unhide all LOD objects in the view layer before selection
        for obj in export_objects:
            try:
                obj.hide_set(False, view_layer=context.view_layer)
                obj.hide_viewport = False
            except (RuntimeError, AttributeError) as exc:
                logger.debug("Could not unhide object %s in view layer: %s", getattr(obj, "name", "unknown"), exc)

        # Unhide colliders and rename to UCX_{asset_name}_{idx:02d} for UE5
        orig_collider_names: dict[Any, str] = {}
        for idx, c_obj in enumerate(collider_objects, start=1):
            try:
                c_obj.hide_set(False, view_layer=context.view_layer)
                c_obj.hide_viewport = False
                orig_collider_names[c_obj] = c_obj.name
                c_obj.name = f"UCX_{asset_name}_{idx:02d}"
            except (RuntimeError, AttributeError) as exc:
                logger.debug("Could not prepare collider %s: %s", getattr(c_obj, "name", "unknown"), exc)

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
            # Skeletal Mesh export branch: select Armature, LOD meshes, and Colliders
            armature_obj.select_set(True)
            for obj in export_objects:
                obj.select_set(True)
            for c_obj in collider_objects:
                c_obj.select_set(True)
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

            # Visual LODs MUST be parented to lod_group_empty
            for obj in export_objects:
                if obj.parent != lod_group_empty:
                    obj.parent = lod_group_empty

            # Colliders MUST remain top-level siblings OUTSIDE lod_group_empty
            for c_obj in collider_objects:
                if c_obj.parent == lod_group_empty:
                    c_obj.parent = None

            lod_group_empty.select_set(True)
            for obj in export_objects:
                obj.select_set(True)
            for c_obj in collider_objects:
                c_obj.select_set(True)
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
        finally:
            # Restore original collider names in Blender
            for c_obj, orig_name in orig_collider_names.items():
                try:
                    c_obj.name = orig_name
                except Exception as exc:
                    logger.debug("Restoring collider name failed: %s", exc)
