"""
Master Engine Export Router & Pre-Flight Quality Gate with PBR Texture, Animation & Live Bridge Integration.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    import bpy
except ImportError:
    bpy = None


logger = logging.getLogger(__name__)


class PreFlightValidator:
    @staticmethod
    def run_checks(context: Any) -> list[str]:
        if not context or not getattr(context, "scene", None):
            return ["Blender context not available."]
        props = getattr(context.scene, "lod_tool", None)
        if not props:
            return ["LOD tool properties not initialized on scene."]
        errors: list[str] = []

        if len(props.lods) == 0:
            errors.append("No LOD tiers configured.")
            return errors

        valid_objs = []
        for tier in props.lods:
            try:
                obj = tier.generated_obj
                obj_name = getattr(obj, "name", None)
                if obj and (not bpy or (isinstance(obj_name, str) and obj_name in bpy.data.objects)):
                    valid_objs.append(obj)
            except (ReferenceError, AttributeError, KeyError) as exc:
                logger.debug("Failed to resolve tier generated_obj: %s", exc)

        if len(valid_objs) != len(props.lods):
            errors.append("Some configured LOD tiers have not been generated yet. Run 'Generate All LODs' first.")
            return errors

        # Empty geometry check
        for i, obj in enumerate(valid_objs):
            if (
                getattr(obj, "type", "") == "MESH"
                and getattr(obj, "data", None)
                and hasattr(obj.data, "polygons")
                and len(obj.data.polygons) == 0
            ):
                errors.append(f"LOD{i} ('{obj.name}') has 0 polygons (empty geometry).")

        # Pivot / origin matching
        lod0_pivot = valid_objs[0].matrix_world.translation if hasattr(valid_objs[0], "matrix_world") else None
        for i, obj in enumerate(valid_objs):
            if lod0_pivot and hasattr(obj, "matrix_world"):
                if (obj.matrix_world.translation - lod0_pivot).length > 1e-4:
                    errors.append(f"LOD{i} origin does not match LOD0 pivot.")

            scale = getattr(obj, "scale", None)
            if scale:
                sx = getattr(scale, "x", scale[0] if isinstance(scale, (list, tuple)) else 1.0)
                sy = getattr(scale, "y", scale[1] if isinstance(scale, (list, tuple)) else 1.0)
                sz = getattr(scale, "z", scale[2] if isinstance(scale, (list, tuple)) else 1.0)
                if abs(sx - 1.0) > 1e-4 or abs(sy - 1.0) > 1e-4 or abs(sz - 1.0) > 1e-4:
                    errors.append(
                        f"LOD{i} has unapplied scale ({round(sx, 2)}, {round(sy, 2)}, {round(sz, 2)}). Apply transforms."
                    )

        # Material checks
        for i, obj in enumerate(valid_objs):
            if len(getattr(obj, "material_slots", [])) == 0 and len(getattr(valid_objs[0], "material_slots", [])) > 0:
                errors.append(f"LOD{i} is missing material slots.")
            for slot_idx, slot in enumerate(getattr(obj, "material_slots", [])):
                if slot.material is None:
                    errors.append(f"LOD{i} has unassigned material in slot {slot_idx}.")

        # Asset name validation
        if props.export_base_name:
            import re

            if re.search(r'[<>:"/\\|?*\x00-\x1f]', props.export_base_name):
                errors.append(f"Export asset name '{props.export_base_name}' contains invalid characters.")

        # Export directory validation
        export_dir_str = props.export_directory.strip() if props.export_directory else ""
        if not export_dir_str:
            errors.append("Export directory path is empty.")
        elif "\x00" in export_dir_str:
            errors.append("Export directory path contains invalid null bytes.")

        return errors


try:
    from ui.export_ops import (
        EXPORT_OPS_CLASSES,
        LOD_OT_bake_rig_animation,
        LOD_OT_export_engine_package,
        LOD_OT_pack_pbr_textures,
        LOD_OT_sync_live_bridge,
        LOD_OT_toggle_live_bridge,
        register_export_ops,
        unregister_export_ops,
    )
except (ImportError, ValueError):
    try:
        from ..ui.export_ops import (
            EXPORT_OPS_CLASSES,
            LOD_OT_bake_rig_animation,
            LOD_OT_export_engine_package,
            LOD_OT_pack_pbr_textures,
            LOD_OT_sync_live_bridge,
            LOD_OT_toggle_live_bridge,
            register_export_ops,
            unregister_export_ops,
        )
    except (ImportError, ValueError):
        EXPORT_OPS_CLASSES = ()  # type: ignore
        LOD_OT_bake_rig_animation = None  # type: ignore
        LOD_OT_export_engine_package = None  # type: ignore
        LOD_OT_pack_pbr_textures = None  # type: ignore
        LOD_OT_sync_live_bridge = None  # type: ignore
        LOD_OT_toggle_live_bridge = None  # type: ignore
        register_export_ops = None  # type: ignore
        unregister_export_ops = None  # type: ignore


def register_exporters() -> None:
    """Delegates exporter registration (operators are centrally registered in ui.operators)."""
    pass


def unregister_exporters() -> None:
    """Delegates exporter unregistration (operators are centrally unregistered in ui.operators)."""
    pass
