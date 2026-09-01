"""
Material Optimization Module.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bmesh
    import bpy
except ImportError:
    bpy = None
    bmesh = None


class MaterialOptimizer:
    @staticmethod
    def calculate_material_areas(obj: Any) -> dict[int, float]:
        """
        Calculates cumulative surface area per material slot index on the given mesh object.
        """
        if not obj or not hasattr(obj, "data") or not obj.data:
            return {}
        mesh = obj.data
        if not hasattr(mesh, "polygons") or not hasattr(obj, "material_slots"):
            return {}

        num_slots = len(obj.material_slots)
        if num_slots == 0:
            return {}

        areas: dict[int, float] = {i: 0.0 for i in range(num_slots)}
        for poly in mesh.polygons:
            idx = getattr(poly, "material_index", 0)
            area = getattr(poly, "area", 0.0)
            if idx in areas:
                areas[idx] += area
            elif len(areas) > 0:
                areas[0] += area
        return areas

    @staticmethod
    def get_dominant_material_index(areas: dict[int, float]) -> int:
        """
        Returns the material slot index with the largest surface area.
        """
        if not areas:
            return 0
        return max(areas.items(), key=lambda item: item[1])[0]

    @classmethod
    def consolidate_micro_materials(
        cls, obj: Any, area_crit: float, preserve_slot_indexing: bool = True
    ) -> dict[str, Any]:
        """
        Consolidates negligible/micro-material surfaces (area < area_crit or < 0.5% total area)
        into the dominant material slot.
        """
        if not bpy or not bmesh or not obj or len(obj.material_slots) <= 1:
            return {"consolidated_slots": 0, "faces_reassigned": 0, "slots_purged": 0}

        areas = cls.calculate_material_areas(obj)
        total_area = sum(areas.values())
        if total_area < 1e-6:
            return {"consolidated_slots": 0, "faces_reassigned": 0, "slots_purged": 0}

        dominant_idx = cls.get_dominant_material_index(areas)
        reassigned_slots: set[int] = set()
        faces_reassigned = 0

        for slot_idx, area in areas.items():
            if slot_idx == dominant_idx:
                continue
            if area < area_crit or (area / total_area) < 0.005:
                reassigned_slots.add(slot_idx)

        if not reassigned_slots:
            return {"consolidated_slots": 0, "faces_reassigned": 0, "slots_purged": 0}

        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            bm.faces.ensure_lookup_table()

            for face in bm.faces:
                if face.material_index in reassigned_slots:
                    face.material_index = dominant_idx
                    faces_reassigned += 1

            bm.to_mesh(obj.data)
        finally:
            bm.free()

        obj.data.update()

        slots_purged = 0
        if not preserve_slot_indexing:
            slots_purged = cls.purge_unused_materials(obj)

        return {
            "consolidated_slots": len(reassigned_slots),
            "faces_reassigned": faces_reassigned,
            "slots_purged": slots_purged,
        }

    @staticmethod
    def purge_unused_materials(obj: Any) -> int:
        """
        Removes unused material slots from the mesh object using Blender 5.2 context overrides.
        """
        if not bpy or not obj or not hasattr(obj, "material_slots") or len(obj.material_slots) == 0:
            return 0
        mesh = obj.data
        if not mesh or not hasattr(mesh, "polygons"):
            return 0

        used_indices = {poly.material_index for poly in mesh.polygons}
        initial_slots = len(obj.material_slots)

        for slot_idx in reversed(range(len(obj.material_slots))):
            if slot_idx not in used_indices:
                obj.active_material_index = slot_idx
                try:
                    if hasattr(bpy.context, "temp_override"):
                        with bpy.context.temp_override(object=obj, active_object=obj):
                            bpy.ops.object.material_slot_remove()
                    else:
                        bpy.context.view_layer.objects.active = obj
                        bpy.ops.object.material_slot_remove()
                except (RuntimeError, AttributeError, TypeError) as exc:
                    logger.debug("Material slot remove bypassed: %s", exc)

        return initial_slots - len(obj.material_slots)
