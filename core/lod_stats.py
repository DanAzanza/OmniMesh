"""
OmniMesh LOD Polygon & Metric Statistics.
Provides O(1) triangle counting and baseline LOD0 statistics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence, cast

if TYPE_CHECKING:
    import bmesh
    import bpy

from .modifiers import ModifierManager


def _count_triangles(mesh_data: bpy.types.Mesh | bmesh.types.BMesh | object | None) -> int:
    """Computes true triangle count in O(1) via loop-poly invariant with safe fallback."""
    if not mesh_data:
        return 0
    try:
        loops = mesh_data.loops  # type: ignore[union-attr]
        polys = mesh_data.polygons  # type: ignore[union-attr]
        if loops is not None and polys is not None:
            n_loops = len(loops)
            n_polys = len(polys)
            return max(0, n_loops - 2 * n_polys) if n_polys > 0 else 0
        if polys is not None:
            return sum(max(0, len(cast("Sequence[int]", p.vertices)) - 2) for p in polys)
    except (AttributeError, TypeError):
        pass
    try:
        faces = mesh_data.faces  # type: ignore[union-attr]
        if faces is not None:
            return len(faces)
    except (AttributeError, TypeError):
        pass
    return 0


def _compute_lod0_stats(mesh_objs: list[bpy.types.Object]) -> tuple[int, int]:
    """Calculates initial triangle count and material slot count for LOD0."""
    tier_tris = 0
    tier_mats = sum(len(obj.material_slots) for obj in mesh_objs)
    for obj in mesh_objs:
        if ModifierManager.has_unapplied_modifiers(obj):
            eval_mesh, eval_obj = ModifierManager.get_evaluated_mesh(obj, preserve_armature=True)
            if eval_mesh:
                try:
                    tier_tris += _count_triangles(eval_mesh)
                finally:
                    if eval_obj:
                        eval_obj.to_mesh_clear()
            else:
                tier_tris += _count_triangles(obj.data)
        else:
            tier_tris += _count_triangles(obj.data)
    return tier_tris, tier_mats


__all__ = [
    "_count_triangles",
    "_compute_lod0_stats",
]
