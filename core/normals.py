"""
Blender 5.2+ Normal Management Module.
"""

from __future__ import annotations

from typing import Any

try:
    import bpy
except ImportError:
    bpy = None


class NormalManager:
    @staticmethod
    def ensure_sharp_edge_attribute(mesh: Any) -> Any:
        if not bpy or not mesh:
            return None
        sharp_attr = mesh.attributes.get("sharp_edge")
        if not sharp_attr:
            sharp_attr = mesh.attributes.new(name="sharp_edge", type="BOOLEAN", domain="EDGE")
        return sharp_attr

    @classmethod
    def reproject_custom_split_normals(cls, lod_obj: Any, source_lod0: Any, delta_world: float = 0.1) -> bool:
        if not bpy or not source_lod0 or not lod_obj or source_lod0 == lod_obj:
            return False

        mod_name = "__LOD_NORMAL_TRANSFER__"
        existing_mod = lod_obj.modifiers.get(mod_name)
        if existing_mod:
            lod_obj.modifiers.remove(existing_mod)

        dt_mod = lod_obj.modifiers.new(name=mod_name, type="DATA_TRANSFER")
        dt_mod.object = source_lod0
        dt_mod.use_loop_data = True
        dt_mod.data_types_loops = {"CUSTOM_NORMAL"}
        dt_mod.loop_mapping = "POLYINTERP_LNORPROJ"
        dt_mod.max_distance = max(2.0 * delta_world, 0.02)
        dt_mod.ray_radius = max(delta_world, 0.01)

        bpy.context.view_layer.objects.active = lod_obj
        try:
            bpy.ops.object.modifier_apply(modifier=dt_mod.name)
            cls.ensure_sharp_edge_attribute(lod_obj.data)
            lod_obj.data.update()
            return True
        except Exception:
            if dt_mod.name in lod_obj.modifiers:
                lod_obj.modifiers.remove(dt_mod)
            return False
