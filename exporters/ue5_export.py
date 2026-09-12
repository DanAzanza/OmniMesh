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


try:
    from .engine_export import AssetMeshResolver
except (ImportError, ValueError):
    try:
        from exporters.engine_export import AssetMeshResolver
    except (ImportError, ValueError):
        AssetMeshResolver = None  # type: ignore


class UE5Exporter:
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

        # Collect ordered export objects (LOD0..N)
        export_objects: list[Any] = []
        for tier_idx in sorted(payload.lod_tiers.keys()):
            for obj in payload.lod_tiers[tier_idx]:
                if obj not in export_objects:
                    export_objects.append(obj)

        if not export_objects:
            return False, f"No generated LOD objects found for '{asset_name}'"

        collider_objects = list(payload.collider_objects)
        armature_obj = payload.armature_obj

        # Save transactional state for rollback
        orig_collider_names: dict[Any, str] = {}
        orig_imp_names: dict[Any, str] = {}
        orig_parents: dict[Any, Any] = {obj: obj.parent for obj in export_objects}
        orig_collider_parents: dict[Any, Any] = {c: c.parent for c in collider_objects}
        created_empty = None

        try:
            # Unhide all LOD objects in view layer
            for obj in export_objects:
                try:
                    obj.hide_set(False, view_layer=context.view_layer)
                    obj.hide_viewport = False
                except (RuntimeError, AttributeError) as exc:
                    logger.debug("Could not unhide object %s in view layer: %s", getattr(obj, "name", "unknown"), exc)

                if "_Impostor" in obj.name or bool(obj.get("_is_impostor", False)):
                    orig_imp_names[obj] = obj.name
                    last_lod_idx = max(payload.lod_tiers.keys())
                    obj.name = f"{clean_name}_LOD{last_lod_idx}"

            # Rename colliders to UCX_{asset_name}_{idx:02d}
            for idx, c_obj in enumerate(collider_objects, start=1):
                try:
                    c_obj.hide_set(False, view_layer=context.view_layer)
                    c_obj.hide_viewport = False
                    orig_collider_names[c_obj] = c_obj.name
                    c_obj.name = f"UCX_{clean_name}_{idx:02d}"
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
                armature_obj.select_set(True)
                for obj in export_objects:
                    obj.select_set(True)
                for c_obj in collider_objects:
                    c_obj.select_set(True)
                context.view_layer.objects.active = armature_obj
            else:
                empty_name = f"LODGroup_{clean_name}"
                lod_group_empty = bpy.data.objects.get(empty_name)
                if not lod_group_empty:
                    lod_group_empty = bpy.data.objects.new(empty_name, None)
                    lod_group_empty.empty_display_type = "PLAIN_AXES"
                    context.scene.collection.objects.link(lod_group_empty)
                    created_empty = lod_group_empty
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
                    logger.debug("Could not unhide lod_group_empty: %s", exc)

                lod_group_empty["fbx_type"] = "LodGroup"

                for obj in export_objects:
                    if obj.parent != lod_group_empty:
                        obj.parent = lod_group_empty

                for c_obj in collider_objects:
                    if c_obj.parent == lod_group_empty:
                        c_obj.parent = None

                lod_group_empty.select_set(True)
                for obj in export_objects:
                    obj.select_set(True)
                for c_obj in collider_objects:
                    c_obj.select_set(True)
                context.view_layer.objects.active = lod_group_empty

            fbx_path = os.path.join(export_dir, f"{clean_name}.fbx")
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
            # Transactional rollback: restore parents
            for obj, orig_parent in orig_parents.items():
                try:
                    obj.parent = orig_parent
                except Exception as exc:
                    logger.debug("Restoring object parent failed: %s", exc)
            for c_obj, orig_parent in orig_collider_parents.items():
                try:
                    c_obj.parent = orig_parent
                except Exception as exc:
                    logger.debug("Restoring collider parent failed: %s", exc)

            # Transactional rollback: remove temporary LODGroup empty if created
            if created_empty and hasattr(bpy.data, "objects") and created_empty.name in bpy.data.objects:
                try:
                    bpy.data.objects.remove(created_empty, do_unlink=True)
                except Exception as exc:
                    logger.debug("Removing temporary LODGroup empty failed: %s", exc)

            # Restore original collider names in Blender
            for c_obj, orig_name in orig_collider_names.items():
                try:
                    c_obj.name = orig_name
                except Exception as exc:
                    logger.debug("Restoring collider name failed: %s", exc)

            # Restore original impostor names in Blender
            for imp_obj, orig_name in orig_imp_names.items():
                try:
                    imp_obj.name = orig_name
                except Exception as exc:
                    logger.debug("Restoring impostor name failed: %s", exc)
