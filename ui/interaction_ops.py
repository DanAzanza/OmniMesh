# pyright: reportInvalidTypeForm=none
"""
OmniMesh Interaction Volume Operators.
Exposes operators to spawn non-blocking clickspots and interaction triggers in Blender.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.types import Operator
else:
    try:
        import bpy
        from bpy.types import Operator
    except ImportError:
        bpy = None
        Operator = object

try:
    from ..core.interaction_volumes import create_interaction_volume
    from .utils import resolve_asset_base_name, resolve_effective_asset_name, safe_report
except (ImportError, ValueError):
    from core.interaction_volumes import create_interaction_volume
    from ui.utils import resolve_asset_base_name, resolve_effective_asset_name, safe_report


class OMNIMESH_OT_add_interaction_volume(Operator):
    """Spawns a non-blocking interaction trigger volume / clickspot into {AssetName}_Interactions."""

    bl_idname = "omnimesh.add_interaction_volume"
    bl_label = "Add Clickspot / Trigger"
    bl_description = (
        "Creates a non-blocking interaction volume (Box, Sphere, Cylinder) in {AssetName}_Interactions "
        "configured for MSFS MouseRects, UE5 Overlap, and Unity Triggers"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(bpy and context)

    def execute(self, context: Any) -> set[Any]:
        if not bpy or not context:
            return {"FINISHED"}

        props = getattr(context.scene, "lod_tool", None) if context else None
        interact_props = getattr(props, "interaction", None) if props else None

        active_obj = getattr(context, "active_object", None)
        asset_name = resolve_effective_asset_name(context, props)
        if not asset_name or asset_name in ("AUTO", "NONE"):
            mesh_objs = [active_obj] if active_obj and getattr(active_obj, "type", "") == "MESH" else []
            asset_name = resolve_asset_base_name(context, mesh_objs) if mesh_objs else "Asset"

        shape = getattr(interact_props, "shape", "BOX") if interact_props else "BOX"
        role = getattr(interact_props, "role", "BUTTON") if interact_props else "BUTTON"
        name = getattr(interact_props, "volume_name", "Clickspot") if interact_props else "Clickspot"
        sx = getattr(interact_props, "size_x", 0.08) if interact_props else 0.08
        sy = getattr(interact_props, "size_y", 0.08) if interact_props else 0.08
        sz = getattr(interact_props, "size_z", 0.08) if interact_props else 0.08
        parent_to_active = getattr(interact_props, "parent_to_active", True) if interact_props else True

        active_obj = getattr(context, "active_object", None)
        parent_obj = (
            active_obj if parent_to_active and active_obj and getattr(active_obj, "type", "") == "MESH" else None
        )

        bdata = getattr(context, "blend_data", None) or (bpy.data if bpy and hasattr(bpy, "data") else None)
        if bdata is None:
            return {"CANCELLED"}
        vol = create_interaction_volume(
            context=context,
            asset_name=asset_name,
            name=name,
            shape=shape,
            role=role,
            size=(sx, sy, sz),
            parent_obj=parent_obj,
            blend_data=bdata,
        )

        if not vol:
            safe_report(self, {"ERROR"}, "Failed creating interaction volume.")
            return {"CANCELLED"}

        msg = f"Created interaction volume '{vol.name}' ({role}, {shape})"
        if parent_obj:
            msg += f" parented to '{parent_obj.name}'."
        else:
            msg += "."

        safe_report(self, {"INFO"}, msg)
        return {"FINISHED"}


INTERACTION_OPERATOR_CLASSES = (OMNIMESH_OT_add_interaction_volume,)


def register():
    from .rna_helpers import register_classes

    register_classes(bpy, INTERACTION_OPERATOR_CLASSES, logger_inst=logger)


def unregister():
    from .rna_helpers import unregister_classes

    unregister_classes(bpy, INTERACTION_OPERATOR_CLASSES, logger_inst=logger)
