"""
OmniMesh Modifier Manager & Non-Destructive Evaluated Mesh Extraction.
Architected for Blender 4.2+ LTS & Blender 5.2 LTS.
Features:
- ModifierManager.get_evaluated_mesh: Extracts baked surface geometry via depsgraph,
  preserving custom normals, UVs, and vertex attributes without mutating source objects.
- ModifierManager.apply_all_modifiers_in_place: Safely applies modifier stack on target object,
  unlinking multi-user meshes and preserving Armature deform modifiers.
- ModifierManager.has_unapplied_modifiers: Fast stack inspection for non-destructive pipelines.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("OmniMesh.Modifiers")

try:
    import bpy
except ImportError:
    bpy = None


class ModifierManager:
    """Handles safe evaluation, inspection, and application of Blender modifiers."""

    @staticmethod
    def has_unapplied_modifiers(obj: Any, ignore_armature: bool = True) -> bool:
        """Returns True if the object has one or more unapplied non-armature modifiers."""
        if not obj or not hasattr(obj, "modifiers"):
            return False
        for mod in obj.modifiers:
            if ignore_armature and getattr(mod, "type", "") == "ARMATURE":
                continue
            return True
        return False

    @staticmethod
    def sync_viewport_to_render_settings(obj: Any) -> int:
        """
        Synchronizes render settings to match viewport settings across all modifiers on obj.
        Ensures that modifier application and evaluated mesh extraction accurately reflect
        the interactive viewport representation (e.g. render_levels = levels, show_render = show_viewport).
        Returns the count of modifiers updated.
        """
        if not obj or not hasattr(obj, "modifiers"):
            return 0

        synced_count = 0
        for mod in obj.modifiers:
            mod_synced = False

            # 1. Subsurf & Multires: sync render_levels to levels
            if hasattr(mod, "levels") and hasattr(mod, "render_levels"):
                if getattr(mod, "render_levels", None) != getattr(mod, "levels", None):
                    try:
                        mod.render_levels = mod.levels
                        mod_synced = True
                    except Exception as exc:
                        logger.debug("Could not sync render_levels on %s: %s", getattr(mod, "name", "mod"), exc)

            # 2. Screw: sync render_steps to steps
            if hasattr(mod, "steps") and hasattr(mod, "render_steps"):
                if getattr(mod, "render_steps", None) != getattr(mod, "steps", None):
                    try:
                        mod.render_steps = mod.steps
                        mod_synced = True
                    except Exception as exc:
                        logger.debug("Could not sync render_steps on %s: %s", getattr(mod, "name", "mod"), exc)

            # 3. Ocean: sync resolution to viewport_resolution
            if hasattr(mod, "viewport_resolution") and hasattr(mod, "resolution"):
                if getattr(mod, "resolution", None) != getattr(mod, "viewport_resolution", None):
                    try:
                        mod.resolution = mod.viewport_resolution
                        mod_synced = True
                    except Exception as exc:
                        logger.debug("Could not sync ocean resolution on %s: %s", getattr(mod, "name", "mod"), exc)

            # 4. Global visibility: sync show_render to show_viewport
            if hasattr(mod, "show_viewport") and hasattr(mod, "show_render"):
                if getattr(mod, "show_render", None) != getattr(mod, "show_viewport", None):
                    try:
                        mod.show_render = mod.show_viewport
                        mod_synced = True
                    except Exception as exc:
                        logger.debug("Could not sync show_render on %s: %s", getattr(mod, "name", "mod"), exc)

            if mod_synced:
                synced_count += 1

        if synced_count > 0:
            logger.info(
                "Synchronized viewport settings to render on %d modifier(s) for %s",
                synced_count,
                getattr(obj, "name", "obj"),
            )

        return synced_count

    @staticmethod
    def get_evaluated_mesh(
        obj: Any,
        depsgraph: Any = None,
        preserve_armature: bool = True,
        max_poly_limit: int = 25_000_000,
    ) -> tuple[Any, Any]:
        """
        Extracts an evaluated mesh datablock with non-armature modifiers baked.
        Returns a tuple of (eval_mesh, eval_obj) where eval_obj must be cleaned up
        via eval_obj.to_mesh_clear() when done.
        """
        if not bpy or not obj or getattr(obj, "type", "") != "MESH":
            return getattr(obj, "data", None), None

        # Synchronize viewport settings into render settings
        ModifierManager.sync_viewport_to_render_settings(obj)

        if depsgraph is None and hasattr(bpy.context, "evaluated_depsgraph_get"):
            depsgraph = bpy.context.evaluated_depsgraph_get()

        if not depsgraph or not hasattr(obj, "evaluated_get"):
            return getattr(obj, "data", None), None

        # Temporarily disable armature modifiers if requested to prevent skin deformation
        disabled_armatures: list[Any] = []
        if preserve_armature and hasattr(obj, "modifiers"):
            for mod in obj.modifiers:
                if getattr(mod, "type", "") == "ARMATURE" and getattr(mod, "show_viewport", False):
                    mod.show_viewport = False
                    disabled_armatures.append(mod)

        try:
            eval_obj = obj.evaluated_get(depsgraph)
            if not eval_obj:
                return getattr(obj, "data", None), None

            raw_polys = len(getattr(eval_obj.data, "polygons", []))
            if raw_polys > max_poly_limit:
                logger.warning(
                    "Evaluated polygon count (%d) exceeds safety threshold (%d)",
                    raw_polys,
                    max_poly_limit,
                )

            if hasattr(eval_obj, "to_mesh"):
                eval_mesh = eval_obj.to_mesh()
                return eval_mesh, eval_obj
            return getattr(eval_obj, "data", None), None

        except Exception as exc:
            logger.error("Failed to extract evaluated mesh for %s: %s", getattr(obj, "name", "obj"), exc)
            return getattr(obj, "data", None), None

        finally:
            for mod in disabled_armatures:
                mod.show_viewport = True

    @staticmethod
    def apply_all_modifiers_in_place(obj: Any, preserve_armature: bool = True) -> bool:
        """
        Applies all non-armature modifiers directly to the object in stack order.
        Synchronizes viewport settings into render settings, removes viewport-hidden modifiers,
        and safely unlinks multi-user mesh data before applying.
        """
        if not bpy or not obj or getattr(obj, "type", "") != "MESH":
            return False

        if not hasattr(obj, "modifiers") or len(obj.modifiers) == 0:
            return True

        # 1. Synchronize viewport settings into render settings so render properties match viewport
        ModifierManager.sync_viewport_to_render_settings(obj)

        # 2. Unlink multi-user mesh data to prevent "Modifier cannot be applied to a multi-user mesh" crash
        if hasattr(obj, "data") and obj.data and getattr(obj.data, "users", 0) > 1:
            try:
                obj.data = obj.data.copy()
                logger.info("Unlinked multi-user mesh data for %s prior to applying modifiers", obj.name)
            except Exception as exc:
                logger.warning("Failed unlinking multi-user mesh for %s: %s", obj.name, exc)

        # 3. Iterate and apply modifiers top-to-bottom
        applied_count = 0
        for mod in list(obj.modifiers):
            if preserve_armature and getattr(mod, "type", "") == "ARMATURE":
                continue

            # Remove modifiers that are disabled in the viewport so they don't get baked
            if not getattr(mod, "show_viewport", True):
                try:
                    obj.modifiers.remove(mod)
                    logger.info(
                        "Removed viewport-hidden modifier %s from %s",
                        getattr(mod, "name", "mod"),
                        obj.name,
                    )
                except Exception as exc:
                    logger.debug(
                        "Could not remove hidden modifier %s: %s",
                        getattr(mod, "name", "mod"),
                        exc,
                    )
                continue

            mod_name = getattr(mod, "name", "modifier")
            try:
                if hasattr(bpy.context, "temp_override"):
                    with bpy.context.temp_override(active_object=obj, object=obj, selected_objects=[obj]):
                        bpy.ops.object.modifier_apply(modifier=mod_name)
                elif hasattr(bpy.context, "view_layer") and hasattr(bpy.context.view_layer, "objects"):
                    bpy.context.view_layer.objects.active = obj
                    bpy.ops.object.modifier_apply(modifier=mod_name)
                applied_count += 1
            except Exception as exc:
                logger.warning("Could not apply modifier %s on %s: %s", mod_name, obj.name, exc)

        logger.info("Applied %d modifiers in-place on %s", applied_count, obj.name)
        return True
