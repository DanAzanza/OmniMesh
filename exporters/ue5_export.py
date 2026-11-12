"""
Unreal Engine 5 (UE5) Exporter for Static & Skeletal LOD Meshes and UCX Collision Hulls.
"""

from __future__ import annotations

try:
    from ..core.exceptions import OmniMeshError
except (ImportError, ValueError):
    from core.exceptions import OmniMeshError

import logging
import os
import re
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.types import BlendData
    import mathutils
    from .base import EngineExporterBase
    from .engine_export import AssetMeshResolver
else:
    try:
        import bpy
        import mathutils
    except ImportError:
        bpy = None
        mathutils = None
    BlendData = object

    from .base import EngineExporterBase
    from .engine_export import AssetMeshResolver


class UE5Exporter(EngineExporterBase):
    @classmethod
    def export_asset(
        cls,
        context: bpy.types.Context | None,
        export_dir: str,
        asset_name: str,
        **kwargs: object,
    ) -> tuple[bool, str]:
        if not bpy or not context:
            return False, "Blender bpy not available."
        clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(asset_name)).strip() or "SM_Asset"

        try:
            os.makedirs(export_dir, exist_ok=True)
        except OSError as exc:
            return False, f"Failed creating export directory '{export_dir}': {exc}"

        bdata_in = kwargs.get("blend_data")
        bdata: BlendData | None = bdata_in if isinstance(bdata_in, BlendData) else context.blend_data
        bdata_objs = bdata.objects if bdata else None
        payload = (
            AssetMeshResolver.resolve_payload(context, clean_name, blend_data=bdata) if AssetMeshResolver else None
        )
        if not payload or not payload.lod_tiers:
            return False, f"No generated LOD objects found for '{asset_name}'"

        prep_warnings: list[str] = []
        cleanup_warnings: list[str] = []

        if context.mode != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except (RuntimeError, AttributeError, TypeError) as exc:
                prep_warnings.append(f"mode_set: {exc}")
                logger.debug("Mode set to OBJECT skipped: %s", exc)

        # Collect ordered export objects (LOD0..N)
        export_objects: list[bpy.types.Object] = []
        for tier_idx in sorted(payload.lod_tiers.keys()):
            for obj in payload.lod_tiers[tier_idx]:
                if obj not in export_objects:
                    export_objects.append(obj)

        if not export_objects:
            return False, f"No generated LOD objects found for '{asset_name}'"

        collider_objects = list(payload.collider_objects)
        armature_obj = payload.armature_obj

        # Save transactional state for rollback
        vl = context.view_layer
        orig_active = vl.objects.active if (vl and vl.objects is not None) else None
        orig_selected = list(context.selected_objects or ())
        all_export_items = export_objects + collider_objects + ([armature_obj] if armature_obj else [])
        orig_hide_states: dict[bpy.types.Object, tuple[bool, bool]] = {}
        for o in all_export_items:
            if not o:
                continue
            hv = o.hide_viewport
            hg = o.hide_get(view_layer=vl) if vl else hv
            orig_hide_states[o] = (hv, hg)

        orig_collider_names: dict[bpy.types.Object, str] = {}
        orig_imp_names: dict[bpy.types.Object, str] = {}
        orig_parents: dict[bpy.types.Object, bpy.types.Object | None] = {obj: obj.parent for obj in export_objects}
        orig_collider_parents: dict[bpy.types.Object, bpy.types.Object | None] = {c: c.parent for c in collider_objects}
        orig_matrices: dict[bpy.types.Object, mathutils.Matrix] = {}
        created_empty = None
        lod_group_empty = None

        try:
            # Unhide all export items in view layer
            for obj in all_export_items:
                try:
                    obj.hide_set(False, view_layer=context.view_layer)
                    obj.hide_viewport = False
                except (RuntimeError, AttributeError) as exc:
                    prep_warnings.append(f"unhide {obj.name}: {exc}")
                    logger.debug("Could not unhide object %s: %s", obj.name, exc)

            # Handle impostor naming convention for UE5
            if payload.has_impostor_tier:
                imp_tier_idx = max(payload.lod_tiers.keys())
                for obj in payload.lod_tiers[imp_tier_idx]:
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
                    prep_warnings.append(f"collider {c_obj.name}: {exc}")
                    logger.debug("Could not prepare collider %s: %s", c_obj.name, exc)

            if armature_obj:
                try:
                    armature_obj.hide_set(False, view_layer=context.view_layer)
                    armature_obj.hide_viewport = False
                except (RuntimeError, AttributeError) as exc:
                    prep_warnings.append(f"armature {armature_obj.name}: {exc}")
                    logger.debug("Could not unhide armature %s in view layer: %s", armature_obj.name, exc)

            bpy.ops.object.select_all(action="DESELECT")

            is_chunked_asset = any(len(objs) > 1 for objs in payload.lod_tiers.values())
            if armature_obj:
                armature_obj.select_set(True)
                for obj in export_objects:
                    obj.select_set(True)
                for c_obj in collider_objects:
                    c_obj.select_set(True)
                context.view_layer.objects.active = armature_obj
            elif is_chunked_asset:
                # For chunked / HLOD assets with multiple objects per tier, bypass single LodGroup empty
                # to avoid UE5 importing each individual chunk as a distinct sequential LOD tier.
                for obj in export_objects:
                    obj.select_set(True)
                for c_obj in collider_objects:
                    c_obj.select_set(True)
                context.view_layer.objects.active = export_objects[0]
            else:
                empty_name = f"LODGroup_{clean_name}"
                lod_group_empty = bdata_objs.get(empty_name) if bdata_objs else None
                if not lod_group_empty and bdata_objs:
                    lod_group_empty = bdata_objs.new(empty_name, None)
                    lod_group_empty.empty_display_type = "PLAIN_AXES"
                    context.scene.collection.objects.link(lod_group_empty)
                    created_empty = lod_group_empty
                elif lod_group_empty is not None:
                    if lod_group_empty.name not in context.scene.collection.objects:
                        try:
                            context.scene.collection.objects.link(lod_group_empty)
                        except RuntimeError as exc:
                            prep_warnings.append(f"link empty: {exc}")
                            logger.debug("LODGroup empty already linked: %s", exc)

                if lod_group_empty is None:
                    return False, f"Could not create or retrieve LODGroup empty for '{clean_name}'."

                try:
                    lod_group_empty.hide_set(False, view_layer=context.view_layer)
                    lod_group_empty.hide_viewport = False
                except (RuntimeError, AttributeError) as exc:
                    prep_warnings.append(f"unhide empty: {exc}")
                    logger.debug("Could not unhide lod_group_empty: %s", exc)

                lod_group_empty["fbx_type"] = "LodGroup"
                if mathutils:
                    lod_group_empty.matrix_world = mathutils.Matrix.Identity(4)

                orig_matrices = {
                    obj: obj.matrix_world.copy()
                    for obj in export_objects + collider_objects
                    if obj.matrix_world is not None
                }
                for obj in export_objects:
                    if obj.parent != lod_group_empty:
                        obj.parent = lod_group_empty
                        if obj in orig_matrices:
                            obj.matrix_world = orig_matrices[obj]

                for c_obj in collider_objects:
                    if c_obj.parent == lod_group_empty or c_obj.parent is not None:
                        c_obj.parent = None
                        if c_obj in orig_matrices:
                            c_obj.matrix_world = orig_matrices[c_obj]

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
                bake_space_transform=False if (armature_obj or lod_group_empty) else True,
                object_types={"ARMATURE", "MESH", "EMPTY"} if armature_obj else {"MESH", "EMPTY"},
                mesh_smooth_type="FACE",
                add_leaf_bones=False if armature_obj else True,
                primary_bone_axis="Y",
                secondary_bone_axis="X",
                armature_nodetype="NULL",
            )
            return True, f"UE5 FBX package exported to: {fbx_path}"
        except (
            OmniMeshError,
            RuntimeError,
            ValueError,
            TypeError,
            AttributeError,
            LookupError,
            OSError,
            ReferenceError,
            ZeroDivisionError,
        ) as e:
            return False, f"Failed to export UE5 FBX: {str(e)}"
        finally:
            # Transactional rollback: restore parents and world matrices
            for obj, orig_parent in orig_parents.items():
                try:
                    obj.parent = orig_parent
                    if obj in orig_matrices:
                        obj.matrix_world = orig_matrices[obj]
                except (RuntimeError, AttributeError, ReferenceError, TypeError) as exc:
                    cleanup_warnings.append(f"parent restore: {exc}")
                    logger.debug("Restoring object parent failed: %s", exc)
            for c_obj, orig_parent in orig_collider_parents.items():
                try:
                    c_obj.parent = orig_parent
                    if c_obj in orig_matrices:
                        c_obj.matrix_world = orig_matrices[c_obj]
                except (RuntimeError, AttributeError, ReferenceError, TypeError) as exc:
                    cleanup_warnings.append(f"collider parent restore: {exc}")
                    logger.debug("Restoring collider parent failed: %s", exc)

            # Transactional rollback: remove temporary LODGroup empty if created
            if created_empty and bdata_objs and created_empty.name in bdata_objs:
                try:
                    bdata_objs.remove(created_empty, do_unlink=True)
                except (RuntimeError, AttributeError, ReferenceError, TypeError) as exc:
                    cleanup_warnings.append(f"remove empty: {exc}")
                    logger.debug("Removing temporary LODGroup empty failed: %s", exc)

            # Restore original collider names in Blender
            for c_obj, orig_name in orig_collider_names.items():
                try:
                    c_obj.name = orig_name
                except (RuntimeError, AttributeError, ReferenceError, TypeError) as exc:
                    cleanup_warnings.append(f"collider name restore: {exc}")
                    logger.debug("Restoring collider name failed: %s", exc)

            # Restore original impostor names in Blender
            for imp_obj, orig_name in orig_imp_names.items():
                try:
                    imp_obj.name = orig_name
                except (RuntimeError, AttributeError, ReferenceError, TypeError) as exc:
                    cleanup_warnings.append(f"impostor name restore: {exc}")
                    logger.debug("Restoring impostor name failed: %s", exc)

            # Restore original hide states
            for obj, (hv, hg) in orig_hide_states.items():
                try:
                    obj.hide_viewport = hv
                    if vl:
                        obj.hide_set(hg, view_layer=vl)
                except (RuntimeError, AttributeError, ReferenceError) as exc:
                    cleanup_warnings.append(f"hide state restore: {exc}")
                    logger.debug("Could not restore hide state: %s", exc)

            # Restore original selection and active object
            if bpy:
                try:
                    bpy.ops.object.select_all(action="DESELECT")
                    for o in orig_selected:
                        o.select_set(True)
                    if vl and vl.objects is not None and orig_active:
                        vl.objects.active = orig_active
                except (RuntimeError, AttributeError, ReferenceError) as exc:
                    cleanup_warnings.append(f"selection restore: {exc}")
                    logger.debug("Could not restore selection state: %s", exc)

            if cleanup_warnings:
                logger.warning(
                    "UE5 export cleanup finished with %d warning(s): %s",
                    len(cleanup_warnings),
                    "; ".join(cleanup_warnings),
                )
