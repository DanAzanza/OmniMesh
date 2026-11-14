"""
OmniMesh Modifier Manager & Non-Destructive Evaluated Mesh Extraction.
Architected for Blender 5.0+ & Blender 5.2 LTS.
Features:
- ModifierManager.get_evaluated_mesh: Extracts baked surface geometry via depsgraph,
  preserving custom normals, UVs, and vertex attributes without mutating source objects.
- ModifierManager.apply_all_modifiers_in_place: Safely applies modifier stack on target object,
  unlinking multi-user meshes and preserving Armature deform modifiers.
- ModifierManager.has_unapplied_modifiers: Fast stack inspection for non-destructive pipelines.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from .compat import ensure_unique_mesh_data

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
else:
    try:
        import bpy
    except ImportError:
        bpy = None


class ModifierManager:
    """Handles safe evaluation, inspection, and application of Blender modifiers."""

    @staticmethod
    def has_unapplied_modifiers(obj: bpy.types.Object | None, ignore_armature: bool = True) -> bool:
        """Returns True if the object has one or more unapplied non-armature modifiers."""
        if not obj or obj.modifiers is None:
            return False
        for mod in obj.modifiers:
            if ignore_armature and mod.type == "ARMATURE":
                continue
            return True
        return False

    @staticmethod
    def sync_viewport_to_render_settings(obj: bpy.types.Object | None) -> int:
        """
        Synchronizes render settings to match viewport settings across all modifiers on obj.
        Ensures that modifier application and evaluated mesh extraction accurately reflect
        the interactive viewport representation (e.g. render_levels = levels, show_render = show_viewport).
        Returns the count of modifiers updated.
        """
        if not obj or obj.modifiers is None:
            return 0

        synced_count = 0
        sync_errors = 0
        for mod in obj.modifiers:
            mod_synced = False

            # 1. Subsurf & Multires: sync render_levels to levels
            if mod.type in ("SUBSURF", "MULTIRES"):
                sub_mod = cast("bpy.types.SubsurfModifier", mod)
                try:
                    if sub_mod.render_levels != sub_mod.levels:
                        sub_mod.render_levels = sub_mod.levels
                        mod_synced = True
                except (TypeError, ValueError, AttributeError) as exc:
                    sync_errors += 1
                    logger.debug("Could not sync render_levels on %s: %s", mod.name, exc)

            # 2. Screw: sync render_steps to steps
            elif mod.type == "SCREW":
                screw_mod = cast("bpy.types.ScrewModifier", mod)
                try:
                    if screw_mod.render_steps != screw_mod.steps:
                        screw_mod.render_steps = screw_mod.steps
                        mod_synced = True
                except (TypeError, ValueError, AttributeError) as exc:
                    sync_errors += 1
                    logger.debug("Could not sync render_steps on %s: %s", mod.name, exc)

            # 3. Ocean: sync resolution to viewport_resolution
            elif mod.type == "OCEAN":
                ocean_mod = cast("bpy.types.OceanModifier", mod)
                try:
                    if ocean_mod.resolution != ocean_mod.viewport_resolution:
                        ocean_mod.resolution = ocean_mod.viewport_resolution
                        mod_synced = True
                except (TypeError, ValueError, AttributeError) as exc:
                    sync_errors += 1
                    logger.debug("Could not sync ocean resolution on %s: %s", mod.name, exc)

            # 4. Global visibility: sync show_render to show_viewport
            try:
                if mod.show_render != mod.show_viewport:
                    mod.show_render = mod.show_viewport
                    mod_synced = True
            except (TypeError, ValueError, AttributeError) as exc:
                sync_errors += 1
                logger.debug("Could not sync show_render on %s: %s", mod.name, exc)

            if mod_synced:
                synced_count += 1

        if synced_count > 0 or sync_errors > 0:
            logger.info(
                "Synchronized viewport settings to render on %d modifier(s) for %s (%d error(s))",
                synced_count,
                obj.name,
                sync_errors,
            )

        return synced_count

    @staticmethod
    def get_evaluated_mesh(
        obj: bpy.types.Object | None,
        depsgraph: bpy.types.Depsgraph | None = None,
        preserve_armature: bool = True,
        max_poly_limit: int = 25_000_000,
        context: bpy.types.Context | None = None,
    ) -> tuple[bpy.types.Mesh | None, bpy.types.Object | None]:
        """
        Extracts an evaluated mesh datablock with non-armature modifiers baked.
        Returns a tuple of (eval_mesh, eval_obj) where eval_obj must be cleaned up
        via eval_obj.to_mesh_clear() when done.
        """
        if not bpy or not obj or obj.type != "MESH":
            return cast(Any, obj.data) if obj else None, None

        # Synchronize viewport settings into render settings
        ModifierManager.sync_viewport_to_render_settings(obj)

        # Temporarily disable armature modifiers BEFORE evaluating depsgraph so skin deformation is excluded
        disabled_armatures: list[bpy.types.Modifier] = []
        if preserve_armature and obj.modifiers is not None:
            for mod in obj.modifiers:
                if mod.type == "ARMATURE" and mod.show_viewport:
                    mod.show_viewport = False
                    disabled_armatures.append(mod)

        ctx = context
        try:
            if depsgraph is None and ctx:
                if ctx.view_layer is not None:
                    ctx.view_layer.update()
                depsgraph = ctx.evaluated_depsgraph_get()

            if not depsgraph:
                return cast(Any, obj.data), None

            eval_obj = obj.evaluated_get(depsgraph)
            if not eval_obj:
                return cast(Any, obj.data), None

            eval_data = cast("bpy.types.Mesh | None", eval_obj.data)
            raw_polys = len(eval_data.polygons) if eval_data and eval_data.polygons is not None else 0
            if raw_polys > max_poly_limit:
                logger.warning(
                    "Evaluated polygon count (%d) exceeds safety threshold (%d)",
                    raw_polys,
                    max_poly_limit,
                )

            eval_mesh = eval_obj.to_mesh()
            if eval_mesh is not None:
                return eval_mesh, eval_obj
            return cast(Any, eval_obj.data), None

        except (RuntimeError, AttributeError, ValueError) as exc:
            logger.error("Failed to extract evaluated mesh for %s: %s", obj.name, exc)
            return cast(Any, obj.data), None

        finally:
            for mod in disabled_armatures:
                mod.show_viewport = True

    @staticmethod
    def apply_all_modifiers_in_place(
        obj: bpy.types.Object | None,
        preserve_armature: bool = True,
        context: bpy.types.Context | None = None,
    ) -> bool:
        """
        Applies all non-armature modifiers directly to the object in stack order.
        Synchronizes viewport settings into render settings, removes viewport-hidden modifiers,
        and safely unlinks multi-user mesh data before applying.
        """
        if not bpy or not obj or obj.type != "MESH":
            return False

        if not obj.modifiers or len(obj.modifiers) == 0:
            return True

        # 1. Synchronize viewport settings into render settings so render properties match viewport
        ModifierManager.sync_viewport_to_render_settings(obj)

        # 2. Unlink multi-user mesh data to prevent "Modifier cannot be applied to a multi-user mesh" crash
        if not ensure_unique_mesh_data(obj):
            logger.warning("Aborting modifier application on multi-user mesh %s", obj.name)
            return False

        # 3. Iterate and apply modifiers top-to-bottom
        applied_count = 0
        failed_count = 0
        ctx = context
        for mod in list(obj.modifiers):
            if preserve_armature and mod.type == "ARMATURE":
                continue

            # Remove modifiers that are disabled in the viewport so they don't get baked
            if not mod.show_viewport:
                try:
                    obj.modifiers.remove(mod)
                    logger.info(
                        "Removed viewport-hidden modifier %s from %s",
                        mod.name,
                        obj.name,
                    )
                except (RuntimeError, AttributeError, ReferenceError) as exc:
                    mod.show_render = False
                    logger.debug(
                        "Could not remove hidden modifier %s: %s",
                        mod.name,
                        exc,
                    )
                continue

            mod_name = mod.name
            try:
                if ctx:
                    with cast(Any, ctx.temp_override)(active_object=obj, object=obj, selected_objects=[obj]):
                        bpy.ops.object.modifier_apply(modifier=mod_name)
                else:
                    bpy.ops.object.modifier_apply(modifier=mod_name)
                applied_count += 1
            except (RuntimeError, AttributeError, TypeError) as exc:
                failed_count += 1
                logger.warning("Could not apply modifier %s on %s: %s", mod_name, obj.name, exc)

        logger.info("Applied %d modifiers in-place on %s (%d failed)", applied_count, obj.name, failed_count)
        return True
