"""
OmniMesh Material Preset Operators.
Exposes UI operators for generating and assigning multi-engine shader presets
(PBR Standard, Glass, Decal, Invisible Collider, Emissive Light) to selected meshes.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bpy
    from bpy.types import Operator
except ImportError:
    bpy = None
    Operator = object

try:
    from ..core.material_presets import assign_material_to_objects, create_or_update_material_preset
    from .utils import safe_report
except (ImportError, ValueError):
    from core.material_presets import assign_material_to_objects, create_or_update_material_preset
    from ui.utils import safe_report


class OMNIMESH_OT_assign_material_preset(Operator):
    """Generates a configured shader material preset and assigns it to selected mesh objects."""

    bl_idname = "omnimesh.assign_material_preset"
    bl_label = "Assign Material Preset"
    bl_description = (
        "Generates a multi-engine shader preset (PBR, Glass, Decal, Collider, Emissive) "
        "and assigns it to active or selected mesh objects with engine tags"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(bpy and context)

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}

        props = getattr(context.scene, "lod_tool", None) if context else None
        mat_props = getattr(props, "material_preset", None) if props else None

        preset_type = getattr(mat_props, "preset_type", "PBR_STANDARD") if mat_props else "PBR_STANDARD"
        mat_name = getattr(mat_props, "material_name", "New_Material") if mat_props else "New_Material"
        base_color = getattr(mat_props, "base_color", (0.8, 0.8, 0.8, 1.0)) if mat_props else (0.8, 0.8, 0.8, 1.0)
        roughness = getattr(mat_props, "roughness", 0.4) if mat_props else 0.4
        metallic = getattr(mat_props, "metallic", 0.0) if mat_props else 0.0
        emission_strength = getattr(mat_props, "emission_strength", 5.0) if mat_props else 5.0
        apply_to_selected = getattr(mat_props, "apply_to_selected", True) if mat_props else True

        mat = create_or_update_material_preset(
            material_name=mat_name,
            preset_type=preset_type,
            base_color=base_color,
            roughness=roughness,
            metallic=metallic,
            emission_strength=emission_strength,
        )

        if not mat:
            safe_report(self, {"ERROR"}, "Failed generating material preset.")
            return {"CANCELLED"}

        assigned_count = 0
        if apply_to_selected:
            targets = list(getattr(context, "selected_objects", []))
            if not targets and getattr(context, "active_object", None):
                targets = [context.active_object]
            assigned_count = assign_material_to_objects(mat, targets)

        msg = f"Created material preset '{mat.name}' ({preset_type})"
        if assigned_count > 0:
            msg += f" and assigned to {assigned_count} object(s)."
        else:
            msg += "."
        safe_report(self, {"INFO"}, msg)
        return {"FINISHED"}


MATERIAL_PRESET_OPERATOR_CLASSES = (OMNIMESH_OT_assign_material_preset,)


def register():
    if not bpy:
        return
    for cls in MATERIAL_PRESET_OPERATOR_CLASSES:
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            logger.debug("Register skipped %s: %s", getattr(cls, "__name__", "cls"), exc)


def unregister():
    if not bpy:
        return
    for cls in reversed(MATERIAL_PRESET_OPERATOR_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:
            logger.debug("Unregister skipped %s: %s", getattr(cls, "__name__", "cls"), exc)
