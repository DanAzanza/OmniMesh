"""
Material Optimization Module.
"""

from __future__ import annotations

from typing import Any

try:
    import bmesh
    import bpy
except ImportError:
    bpy = None
    bmesh = None


class MaterialOptimizer:
    @staticmethod
    def calculate_material_areas(obj: Any) -> dict[int, float]:
        if not bpy or not obj:
            return {}
        mesh = obj.data
        areas: dict[int, float] = {i: 0.0 for i in range(len(obj.material_slots))}
        for poly in mesh.polygons:
            idx = poly.material_index
            if idx in areas:
                areas[idx] += poly.area
        return areas

    @staticmethod
    def get_dominant_material_index(areas: dict[int, float]) -> int:
        if not areas:
            return 0
        return max(areas.items(), key=lambda item: item[1])[0]

    @classmethod
    def consolidate_micro_materials(
        cls, obj: Any, area_crit: float, preserve_slot_indexing: bool = True
    ) -> dict[str, Any]:
        if not bpy or not bmesh or not obj or len(obj.material_slots) <= 1:
            return {"consolidated_slots": 0, "faces_reassigned": 0}

        areas = cls.calculate_material_areas(obj)
        total_area = sum(areas.values())
        if total_area < 1e-6:
            return {"consolidated_slots": 0, "faces_reassigned": 0}

        dominant_idx = cls.get_dominant_material_index(areas)
        reassigned_slots: set[int] = set()
        faces_reassigned = 0

        for slot_idx, area in areas.items():
            if slot_idx == dominant_idx:
                continue
            if area < area_crit or (area / total_area) < 0.005:
                reassigned_slots.add(slot_idx)

        if not reassigned_slots:
            return {"consolidated_slots": 0, "faces_reassigned": 0}

        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.faces.ensure_lookup_table()

        for face in bm.faces:
            if face.material_index in reassigned_slots:
                face.material_index = dominant_idx
                faces_reassigned += 1

        bm.to_mesh(obj.data)
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
        if not bpy or not obj:
            return 0
        mesh = obj.data
        used_indices = {poly.material_index for poly in mesh.polygons}
        initial_slots = len(obj.material_slots)

        for slot_idx in reversed(range(len(obj.material_slots))):
            if slot_idx not in used_indices:
                obj.active_material_index = slot_idx
                bpy.ops.object.material_slot_remove({"object": obj})

        return initial_slots - len(obj.material_slots)
